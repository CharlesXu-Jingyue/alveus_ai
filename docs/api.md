# HTTP API

Served by `alveus talk` (default) and `alveus api` on `http://127.0.0.1:8765`
(`api.host` / `api.port`). Interactive OpenAPI docs at `/docs`. No authentication: it binds to
localhost only; put it behind a reverse proxy with auth if you expose it.

| method & path | body | response | notes |
|---|---|---|---|
| `GET /health` | | `{ok, llm, state, tools, stt, tts}` | `ok` = LLM endpoint reachable and serving the configured model; `state` is idle/listening/thinking/speaking in talk mode |
| `GET /tools` | | `[{name, description, destructive}]` | namespaced tool names as the model sees them |
| `POST /chat` | `{"text": str, "speak": bool=false, "reset": bool=false}` | `{"reply": str}` | runs the agent with tools on the shared conversation history. `speak: true` (talk mode) also voices the reply through the speaker with sentence streaming. `reset` clears history first. Destructive tool calls are refused (no confirmer) unless `speak: true`, where confirmation is spoken |
| `POST /speak` | `{"text": str, "play": bool=false}` | WAV bytes (`audio/wav`), or `{"played": true, "seconds": n}` when `play` | synthesize with the active TTS backend |
| `POST /transcribe` | multipart `file=@audio.wav` | `{"text": str}` | any sample rate/channels; resampled to 16 kHz mono |
| `POST /trigger` | | `{"triggered": bool}` | start listening now (equivalent to the hotkey); `false` in `alveus api` mode |
| `POST /stop` | | `{"stopped": true}` | stop current speech output and drop the queue |

Examples:

```bash
curl -s localhost:8765/health | jq
curl -s localhost:8765/chat -H 'content-type: application/json' \
     -d '{"text": "how much disk space is left?"}'
curl -s localhost:8765/speak -H 'content-type: application/json' \
     -d '{"text": "Build finished."}' -o build.wav
curl -s localhost:8765/transcribe -F file=@memo.wav
```

Python:

```python
import httpx
r = httpx.post("http://127.0.0.1:8765/chat", json={"text": "what's my GPU temperature?"}, timeout=120)
print(r.json()["reply"])
```

Ideas: bind `alveus trigger` (which posts to `/trigger`) to a GNOME keyboard shortcut on Wayland;
have cron or a build script call `/speak` with `play: true` for spoken notifications; feed audio
from a phone or another room's microphone to `/transcribe` + `/chat`.
