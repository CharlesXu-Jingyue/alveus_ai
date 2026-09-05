# Alveus / Aurea — a fully local voice AI assistant

Alveus (or **Aurea**, when it speaks with a female voice) is a Jarvis-style assistant that runs
entirely on your own Linux + NVIDIA machine: local LLM, local speech-to-text, local
text-to-speech, and tool access to your computer through MCP servers. Nothing leaves the box.

```
   mic ──► VAD ──► STT ──► "Aurea, …?" ──► Agent loop ◄──► MCP tools (files, shell, desktop,
                                              │                        system, web, coder/opencode)
                                              ▼
                                   LLM (llama-server / any OpenAI-compatible API)
                                              │
                                   sentence stream ──► TTS ──► speaker
```

Every stage is a pluggable backend chosen in `config/alveus.yaml`:

| stage | default | alternatives (switch in config) |
|---|---|---|
| LLM | Bonsai-27B 1-bit via PrismML llama.cpp (`bonsai-1bit`) | `bonsai-ternary`, or any OpenAI-compatible server (vLLM, Ollama, LM Studio, remote) |
| STT | faster-whisper `large-v3-turbo` (GPU) | NVIDIA Parakeet TDT 0.6B v3 (`parakeet`), any `/v1/audio/transcriptions` server |
| TTS | Kokoro-82M (`af_heart`) | Chatterbox Turbo (voice cloning), any `/v1/audio/speech` server |
| activation | say **Alveus** / **Aurea**, or `ctrl+alt+space` | openWakeWord neural wake word (`hey jarvis` or a custom model) |
| audio I/O | PipeWire (`pw-record`/`pw-play`) | PortAudio via sounddevice |

## Install (any Linux + CUDA machine)

```bash
git clone <this repo> alveus-ai && cd alveus-ai
./install.sh --ternary --with-chatterbox --services     # see ./install.sh --help
conda activate alveus
alveus doctor --warm
```

`install.sh` creates the `alveus` conda env (or `--venv`), installs Python deps, builds the PrismML
llama.cpp fork with CUDA for your GPU, downloads the Bonsai weights, pre-caches the speech models,
writes `config/local.yaml` for the machine, and (with `--services`) installs systemd user units.

Optional desktop tools for full GNOME control: `sudo apt install xdotool wmctrl xclip playerctl`.

## Run

```bash
alveus llm serve            # start the LLM server (or: systemctl --user start alveus-llm)
alveus talk                 # voice assistant; also serves the browser GUI + API on :8765
alveus ui                   # open http://127.0.0.1:8765/ — chat by typing, edit settings, restart
alveus chat                 # text REPL with the same agent + tools
alveus chat --speak         # text in, voice out
```

Try: *"Aurea, what's my GPU temperature?"*, *"Alveus, open Firefox"*, *"turn the volume down"*,
*"what's the weather in Boston?"*, *"list the files in my repo folder"*, *"in ~/local/repo/foo,
add a README"* (delegated to opencode).

Destructive actions (delete, kill, shutdown, risky shell commands) are always confirmed by voice.

## Useful commands

| command | purpose |
|---|---|
| `alveus doctor [--warm]` | check GPU, LLM endpoint, models, deps, audio backend |
| `alveus tools` | list every MCP tool the agent can call |
| `alveus devices` | audio devices (PipeWire sinks/sources) |
| `alveus stt test --seconds 5` | record and transcribe |
| `alveus tts say "hello"` / `alveus tts voices` | speak / list voices |
| `alveus wakeword-test` | live openWakeWord scores for threshold tuning |
| `alveus llm profiles` / `alveus llm test` | LLM profiles / quick prompt |
| `alveus trigger` | make a running assistant listen (bind to a keyboard shortcut on Wayland) |

## Swapping the LLM

Add a profile under `llm.profiles` and set `llm.profile` (or `ALVEUS_LLM_PROFILE=name`):

```yaml
llm:
  profile: qwen-vllm
  profiles:
    qwen-vllm:
      backend: openai
      base_url: http://127.0.0.1:8000/v1
      api_key: local
      model: Qwen/Qwen3-32B
      reasoning: true
```

Profiles with a `serve:` block can be launched by `alveus llm serve --profile NAME`.

## Adding tools

Any MCP server (stdio or HTTP) goes under `tools.servers` in `config/local.yaml`:

```yaml
tools:
  servers:
    home-assistant:
      url: http://homeassistant.local:8123/mcp_server/sse
      headers: { Authorization: "Bearer ${HASS_TOKEN}" }
    my-server:
      command: [npx, -y, some-mcp-server]
```

Built-in servers live in `mcp_servers/` and are plain `MCPServer` (FastMCP) apps; copy one to
add your own. Mark risky tools with `annotations=annot(destructive=True)` to get voice confirmation.

## Browser GUI and HTTP API (from `alveus talk` or `alveus api`)

`http://127.0.0.1:8765/` serves a GUI: chat by typing with streamed replies, tool activity and
Allow/Deny cards for destructive actions, a live view of voice turns, and a Settings tab that edits
`config/local.yaml` and restarts the services. Local machine only; use an SSH tunnel from elsewhere.
API: `POST /chat`, `POST /chat/stream` (SSE), `POST /speak`, `POST /transcribe`, `POST /trigger`,
`POST /stop`, `GET /history`, `GET /events`, `GET/PUT /config`, `POST /restart`, docs at `/docs`.

## Layout

```
alveus/            core package: config, llm/, stt/, tts/, audio/, agent/, voice.py, api.py, cli.py, web/index.html (GUI)
mcp_servers/       built-in MCP servers (files_shell, desktop, system, web, coder)
config/            alveus.yaml (defaults), persona.md, local.yaml (per machine, git-ignored)
scripts/           build_llama.sh, download_models.sh, pip_install_env.sh, install_services.sh, train_wakeword.sh
systemd/           user unit templates
docs/              wake-words.md and more
```

Full documentation: [docs/README.md](docs/README.md), or open `docs/handbook.html` offline in a browser (`alveus handbook`; served at `/handbook` by the GUI) (overview, architecture, installation, configuration reference, usage, tools, backends, API, wake words, troubleshooting, development).
