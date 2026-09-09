# HTTP API and browser GUI

Served by `alveus talk` (default) and `alveus api` on `http://127.0.0.1:8765`
(`api.host` / `api.port`). The **browser GUI** lives at `/` (see [usage.md](usage.md#browser-gui));
interactive OpenAPI docs at `/docs`. No authentication: it binds to localhost only. To use it from
another device, tunnel instead of exposing the port: `ssh -L 8765:127.0.0.1:8765 <host>`.

| method & path | body | response | notes |
|---|---|---|---|
| `GET /health` | | `{ok, llm, state, tools, stt, tts}` | `ok` = LLM endpoint reachable and serving the configured model; `state` is idle/listening/thinking/speaking in talk mode |
| `GET /tools` | | `[{name, description, destructive}]` | namespaced tool names as the model sees them |
| `POST /chat` | `{"text": str, "speak": bool=false, "reset": bool=false}` | `{"reply": str}` | runs the agent with tools on the shared conversation history. `speak: true` (talk mode) also voices the reply through the speaker with sentence streaming. `reset` clears history first. Destructive tool calls are refused (no confirmer) unless `speak: true`, where confirmation is spoken |
| `POST /speak` | `{"text": str, "play": bool=false}` | WAV bytes (`audio/wav`), or `{"played": true, "seconds": n}` when `play` | synthesize with the active TTS backend |
| `POST /transcribe` | multipart `file=@audio.wav` | `{"text": str}` | any sample rate/channels; resampled to 16 kHz mono |
| `POST /trigger` | | `{"triggered": bool}` | start listening now (equivalent to the hotkey); `false` in `alveus api` mode |
| `POST /stop` | | `{"stopped": true}` | stop current speech output and drop the queue |
| `GET /` | | HTML | the browser GUI (chat + settings) |
| `POST /chat/stream` | `{"text": str, "speak": bool=false, "reset": bool=false}` | SSE stream | events: `reasoning`, `content`, `tool_start {tool,args}`, `tool_result {tool,text}`, `confirm {id,description}`, `error`, `done {reply}`. Destructive tools wait for `POST /confirm` (120 s, then denied) |
| `POST /confirm` | `{"id": str, "ok": bool}` | `{"resolved": bool}` | answer a `confirm` event from `/chat/stream` |
| `GET /history` | | `[{role, text, tools:[{name,args,result}]}]` | the shared conversation (voice and GUI turns) |
| `POST /history/reset` | | `{"reset": true}` | clear the conversation |
| `GET /events` | | SSE stream | live `state` (idle/listening/thinking/speaking), `transcript {who,text,source}`, `reset`, `config_saved`, `restarting`, `ping` |
| `GET /config` | | `{effective, local, local_yaml, options, paths, env, managed_by_systemd, running_profile}` | merged configuration plus the machine overrides and option lists for the GUI |
| `PUT /config` | `{"patch": {...}}` or `{"yaml": "..."}` | `{saved, local, local_yaml, restart_required}` | deep-merge into `config/local.yaml` (a `null` leaf stores an explicit null, e.g. auto-detect language; a leaf `{"$unset": true}` removes the override so the default applies) or replace the file; validated before writing |
| `GET /persona` / `PUT /persona` | — / `{"text": str}` | `{text}` / `{saved}` | read/write `config/persona.md` |
| `POST /restart` | `{"what": "assistant" \| "llm" \| "both"}` | `{restarting: [...]}` | restarts the systemd user units; 409 when not running under systemd |

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

Streaming from the shell:

```bash
curl -sN localhost:8765/chat/stream -H 'content-type: application/json' -d '{"text":"what time is it?"}'
```

Ideas: bind `alveus trigger` (which posts to `/trigger`) to a GNOME keyboard shortcut on Wayland;
have cron or a build script call `/speak` with `play: true` for spoken notifications; feed audio
from a phone or another room's microphone to `/transcribe` + `/chat`.
