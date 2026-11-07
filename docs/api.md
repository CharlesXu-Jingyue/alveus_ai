# HTTP API and browser GUI

Served by `alveus talk` (default) and `alveus api` on `http://127.0.0.1:8765`
(`api.host` / `api.port`). The **browser GUI** lives at `/` (see [usage.md](usage.md#browser-gui));
interactive OpenAPI docs at `/docs`. No authentication: it binds to localhost only. To use it from
another device, tunnel instead of exposing the port: `ssh -L 8765:127.0.0.1:8765 <host>`.

| method & path | body | response | notes |
|---|---|---|---|
| `GET /health` | | `{ok, llm, state, tools, stt, tts, profile, llm_provider, llm_model, llm_remote, llm_service, …}` | `ok` = LLM endpoint reachable (local: serving the configured model; cloud: key and model accepted, checked at most once a minute, and a successful reply counts); `state` is idle/listening/thinking/speaking in talk mode; `llm_service` (alveus-llm unit status) only for profiles with a local server |
| `GET /tools` | | `[{name, description, destructive}]` | namespaced tool names as the model sees them |
| `POST /chat` | `{"text": str, "speak": bool=false, "reset": bool=false}` | `{"reply": str}` | runs the agent with tools on the shared conversation history. `speak: true` (talk mode) also voices the reply through the speaker with sentence streaming. `reset` clears history first. Destructive tool calls are refused (no confirmer) unless `speak: true`, where confirmation is spoken |
| `POST /speak` | `{"text": str, "play": bool=false}` | WAV bytes (`audio/wav`), or `{"played": true, "seconds": n}` when `play` | synthesize with the active TTS backend |
| `POST /transcribe` | multipart `file=@audio.wav` | `{"text": str}` | any sample rate/channels; resampled to 16 kHz mono |
| `POST /trigger` | | `{"triggered": bool}` | start listening now (equivalent to the hotkey); `false` in `alveus api` mode |
| `POST /stop` | | `{"stopped": true}` | stop current speech output and drop the queue |
| `POST /interrupt` | | `{"interrupted": true}` | abort the running turn (voice or GUI): stop generating, skip pending tool calls, cut speech, deny open confirmations; the stream then emits `interrupted` and `done` |
| `GET /` | | HTML | the browser GUI (chat + settings) |
| `POST /chat/stream` | `{"text": str, "speak": bool=false, "reset": bool=false}` | SSE stream | events: `reasoning`, `content`, `tool_start {tool,args}`, `tool_result {tool,text}`, `confirm {id,description,sudo}`, `interrupted`, `error`, `done {reply}`. Destructive and sudo tools wait for `POST /confirm` (120 s, then denied) |
| `POST /confirm` | `{"id": str, "ok": bool, "password"?: str}` | `{"resolved": bool}` | answer a `confirm` event from `/chat/stream` or `/events`; when the event has `sudo: true`, `password` is the sudo password for that one command |
| `GET /history` | | `[{role, text, tools:[{name,args,result}]}]` | the shared conversation (voice and GUI turns) |
| `POST /history/reset` | | `{"reset": true}` | clear the conversation |
| `GET /events` | | SSE stream | live `state` (idle/listening/thinking/speaking), `transcript {who,text,source}`, `reset`, `config_saved`, `restarting`, `ping`; and the live progress of voice turns (`source: voice`): `assistant_start`, `assistant_delta {text}`, `tool_start {tool,args}`, `tool_result {tool,text}`, `voice_confirm {text}` (question asked aloud), `confirm {id,description,sudo}` (needs `POST /confirm`), then the final `transcript` |
| `GET /config` | | `{effective, local, local_yaml, options, paths, env, managed_by_systemd, running_profile, llm_profile_info, llm_providers, secrets, running}` | merged configuration plus the machine overrides and option lists for the GUI; `llm_profile_info` = per profile its effective values `{label, provider, model, remote, local_server, model_path, file_exists, temperature, top_p, max_tokens, effort, thinking, context, top_k, base_url, api_key_env}`; `llm_providers` = per provider what the settings page offers (`group`, `title`, `blurb`, `effort_levels`, `thinking_switch`, `sampling`, suggested `models`, `key_source`, `defaults` for a new profile, `serve_template` for local files); `running` = the loaded voice engine (for previews); `secrets` as `GET /secrets` |
| `GET /llm/models?provider=P[&base_url=…]` | | `{models: [{id, name?, note?, file?, path?, portable?, size_gb?}], source, error?, dir?}` | the model picker: GGUF files under `ALVEUS_MODELS` for `llama_server` (`source: files`), else the provider's live list (`live`, needs the key; OpenRouter: tool-capable models only) or the suggested models when that fails (`suggested`, with the reason in `error`). Cached 10 min |
| `GET /audio/devices` | | `{sources: [{name, label}], sinks: [...]}` | PipeWire microphones and speakers (`pw-dump`); `name` is what `audio.input_device` / `output_device` take |
| `POST /tts/preview` | `{"voice": str, "text"?: str}` | WAV | speak a sample sentence with another Kokoro voice of the running engine (any accent; the model is shared); 409 when Kokoro is not the running engine |
| `GET /voices/file?name=N[&dir=D]` | | the WAV | one recording from the voices folder (only names that folder lists), for listening in the browser |
| `GET /secrets` | | `{path, keys: {NAME: {source, profiles, label}}}` | which API-key variables the profiles use and whether each is set (`source`: `env`, `file` or `null`); never the values |
| `PUT /secrets` | `{"name": str, "value": str}` | same as `GET /secrets` | store an API key in `~/.config/alveus/secrets.env` (mode 600); empty `value` removes it. Only variables some profile or provider uses are accepted. Effective from the next request, no restart |
| `POST /llm/check` | `{"profile": str, "definition"?: {…}}` | `{ok, kind, seconds, error?, detail?}` | preflight before switching profiles. Local server profile: llama-server loads the file on the CPU (5–40 s). Cloud/external (`kind`: `cloud`/`external`): key present and accepted, model known; nothing is generated. `definition` checks a profile that is not saved yet (the settings page sends it for a newly picked model) |
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
