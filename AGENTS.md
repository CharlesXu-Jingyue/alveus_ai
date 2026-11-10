# AGENTS.md — orientation for a new session working on Alveus

Read this first. It tells you what the project is, where everything lives, how to run and verify
it, what the owner cares about, and the traps that have already cost time. Written 2026-09-09.

## What this is

Alveus (also called **Aurea** when its voice is female) is a fully local, voice-driven AI
assistant for the owner's Linux workstation. Speech in → local LLM with tools → speech out, plus a
browser GUI. Nothing leaves the machine except the web tools, unless a cloud LLM profile is selected
(then the conversation goes to that provider). Repo: `~/local/repo/alveus-ai`,
conda env `alveus`, Python 3.12. Everything is committed to git on `master`; commit after each
change with a descriptive message (see `git log` for the style).

## Read in this order

1. `README.md` — one-page summary and quick start.
2. `docs/overview.md` — capabilities, measured performance, glossary.
3. `docs/architecture.md` — components, the voice state machine, concurrency, safety model.
4. `docs/configuration.md` — every config key. The config is the API for most changes.
5. The area you are changing: `docs/tools.md` (MCP servers), `docs/backends.md` (LLM/STT/TTS/audio),
   `docs/api.md` (GUI + HTTP API), `docs/wake-words.md`, `docs/troubleshooting.md`,
   `docs/development.md`.
6. Code entry points: `alveus/voice.py` (voice loop), `alveus/agent/loop.py` (tool loop),
   `alveus/api.py` (GUI/API server), `alveus/web/index.html` (the whole GUI, vanilla JS),
   `alveus/cli.py`, `mcp_servers/*.py`, `alveus/config.py`.

`docs/handbook.html` is a generated single-file rendering of `docs/*.md`
(`python scripts/build_handbook.py`); regenerate it whenever docs change and commit both.

## Runtime layout on this machine

| what | where |
|---|---|
| repo / `ALVEUS_HOME` | `~/local/repo/alveus-ai` |
| machine-specific config (git-ignored) | `config/local.yaml` — read it first; defaults are `config/alveus.yaml` |
| models (`ALVEUS_MODELS`) | `/mnt/data/models`: `llm/<model>/*.gguf` (Bonsai 1-bit and ternary, Ternary Bonsai 2, LFM2.5, LFM3, stock Qwen3.8 27B and three variants), `tts/` (Qwen3-TTS), `wakeword/` |
| llama.cpp (PrismML fork, **prism** branch, relocatable build) | `~/local/lib/llama.cpp-bonsai/build/bin/llama-server` |
| voice samples for cloning | `~/local/repo/alveus-ai/voices/` (`tts.voices_dir`, git-ignored): `m_charles_demo.wav` plus six curated female voices (`f_*_ja`, `f_*_zh`) with `.txt` transcripts; sources and terms in `voices/SOURCES.md` |
| Qwen3-TTS | own env `.venv-qwen3tts/` (venv on the alveus Python, transformers 4.57.3), weights `/mnt/data/models/tts/Qwen3-TTS-12Hz-1.7B-Base` (`tts.qwen3.weights_dir`) |
| systemd user units | `~/.config/systemd/user/alveus-llm.service`, `alveus.service` (rendered from `systemd/*.in` by `scripts/install_services.sh`) |
| logs | `journalctl --user -u alveus -f`, `logs/alveus.log` |
| GUI + API | http://127.0.0.1:8765/ (served by the `alveus` service), API docs at `/docs`, handbook at `/handbook` |
| LLM server | http://127.0.0.1:8080/v1 (OpenAI-compatible) |
| API keys for cloud LLM profiles | `~/.config/alveus/secrets.env` (mode 600, outside the repo; `ALVEUS_SECRETS` overrides); GUI writes it via `PUT /secrets`, CLI `alveus llm key NAME` |
| opencode config (coder tool) | `~/.config/opencode/opencode.jsonc`, provider `bonsai` |
| ComfyUI (image generation; Alveus's `images` tools, `mcp_servers/comfy.py`) | checkout `~/local/lib/ComfyUI`, conda env `comfy` (torch cu130), user unit `comfyui.service` on http://127.0.0.1:8188, `RequiresMountsFor=/mnt/data` |
| ComfyUI models | `/mnt/data/comfy/models/{checkpoints,diffusion_models,text_encoders,vae,loras,controlnet,model_patches}` via `extra_model_paths.yaml`; `/mnt/data` is the NTFS "Data" drive (fstab by label, `ntfs3`, uid 1000) |
| generated images | ComfyUI GUI renders: `~/local/lib/ComfyUI/output` (ComfyUI's default). Alveus-made images: `~/local/data/alveus-ai/images` (`tools.servers.images.env.ALVEUS_IMAGES_DIR`; fetched from ComfyUI's temp folder, never in its output) |
| exported workflows (API format) | `config/comfy/*.json`; the images tools use `txt2img_z_image_turbo_demo.json` (new pictures) and `img2img_z_image_turbo_fun_union_controlnet_demo.json` (redrawing) |

Hardware: RTX 4090 24 GB, i9-13900K, 62 GB RAM, Ubuntu 24.04, GNOME on X11, PipeWire audio
(motherboard USB audio + Panasonic SC-GN01 speaker/mic). Root partition is only 195 GB (keep big
downloads on `/mnt/data`); device names (`nvmeXn1`) change between boots, so fstab uses labels.

## Current configuration (check `config/local.yaml`, it may have moved on)

LLM profile `deepseek` (deepseek-v4-pro, disposable test key with ~$10 credit, chosen by the
owner on 2026-11-07); the local `bonsai-ternary` (Ternary-Bonsai-27B, ~89 tok/s) is one click
away. Profiles = provider + model (`alveus/llm/providers.py`); `claude` and `chatgpt` have no key
yet, `qwen-local` has no weights. On a cloud profile the assistant keeps `alveus-llm` stopped. STT faster-whisper large-v3-turbo,
language fixed to `en` unless the owner cleared it. TTS **Chatterbox multilingual** with the cloned
sample `m_demo_charles.wav`; voice gender `auto` (inferred from the `m_`/`f_` file prefix) → the
assistant currently calls itself Alveus. Activation: `mode: both` (names in the transcript plus the custom openWakeWord models
`alveus`/`aurea`, threshold 0.5) plus hotkey ctrl+alt+space. STT language `null` (auto-detect). Both services enabled at login.

## How to work

```bash
conda activate alveus
python -m pytest -q tests && python -m ruff check alveus mcp_servers   # always before committing
alveus doctor --warm            # environment check
alveus chat                     # text REPL with tools (fastest way to test agent changes)
systemctl --user restart alveus # pick up code/config changes in the running assistant
journalctl --user -u alveus -n 100 --no-pager
curl -s localhost:8765/health | python -m json.tool
```

- The running assistant is a **systemd service**. Editing code does nothing until you restart it.
  Stop it (`systemctl --user stop alveus`) before running `alveus talk` by hand, or two instances
  answer the microphone.
- Restarting `alveus-llm` reloads the model (20–40 s). `alveus` restarts in ~10 s (Chatterbox) to
  ~40 s (first-time model downloads).
- Verify the GUI's JavaScript with `node --check` on the extracted `<script>` (see git history for
  the one-liner); there is no build step and no framework.
- Test API behaviour with `curl` against :8765 — `POST /chat`, `POST /chat/stream` (SSE),
  `PUT /config {patch}`, `POST /speak {text, play:true}` (audible on the owner's speaker).
- Never `pkill -f <pattern>` from a shell whose own command line contains the pattern — it kills
  the shell (happened twice). Use pids or `systemctl`.
- Keep `config/local.yaml` intact: it holds the owner's choices. Change it via
  `alveus.config.patch_local_yaml()` or the GUI, not by hand-editing in bulk.

## API keys: never look at them

Cloud LLM keys live in `~/.config/alveus/secrets.env` (or the environment). The owner puts them
there through the GUI or `alveus llm key` in their own terminal. A session working on Alveus must:

- never read, print, grep, copy or summarize `~/.config/alveus/secrets.env`, nor run anything that
  prints environments (`env`, `printenv`, `set`, `systemctl --user show-environment`,
  `/proc/*/environ`, `ps e`) or request headers;
- check whether a key is set only by its source: `alveus llm profiles`, `alveus doctor`,
  `GET /secrets`, or `python -c "from alveus import credentials as c; print(c.source('NAME'))"`;
- never ask the owner to paste a key into the chat, and never export a key in the shell running
  the session (Claude Code itself reads `ANTHROPIC_API_KEY`);
- use the key only by running Alveus (`alveus llm test --profile NAME`, `alveus chat --profile NAME`,
  a test instance); outputs show replies and masked errors, not keys;
- treat cloud requests as paid: say beforehand when a test makes more than a few requests. The
  current test key is a disposable DeepSeek key with about $10 of credit (2026-11-07).

If a key does show up in output anyway, stop, tell the owner to revoke it, and do not repeat it.

## Conventions

- One backend per file under `alveus/llm|stt|tts/`, registered in that package's `__init__`
  factory; heavy imports happen inside `load()`. LLM: one adapter per wire protocol
  (`openai_chat`, `openai_responses`, `anthropic_messages`); providers are presets, not classes.
  The history stays provider-neutral; provider-specific data rides in `_replay` (see `llm/base.py`).
- API keys never go in YAML, never into `os.environ`, never into tool servers' environment
  (`alveus/credentials.py`, `ToolHub.server_env`).
- MCP servers: `from .common import FastMCP, annot, j, run`; return JSON strings; mark irreversible
  tools `annot(destructive=True)` — that is what triggers the spoken/GUI confirmation.
- Config patch semantics (`alveus/config.py`): a `null` leaf stores an explicit null (e.g. language
  auto-detect); `{"$unset": true}` removes the machine override. The GUI relies on this.
- GUI settings are declared in `SECTIONS` in `alveus/web/index.html`: a tree where `t:'choice'`
  items show cards and render the chosen option's `branch[value]` (or `each(value)`) in a nested
  panel; paths may use `{v}` for the chosen value, `fb:` lists inherited values. Model-specific
  settings go under `<engine>.models.<model>` (resolved by `config.engine_opts`) or the LLM profile.
  The language model is a custom block (`llmBlock`: provider → model → that profile's settings).
  `h:` is one plain-language line, `more:` the details; the owner reads them and asks when vague.
- Settings apply without a restart (`alveus/live.py`, `PUT /config` with `apply: true`). A component
  that reads configuration only at start must be handled there (or get a `reconfigure(opts)` method
  returning False when it needs a reload); otherwise list its prefix in `live.RESTART`.
- The system prompt = `config/instructions.md` (directions and boundaries; `{personality}` slot) + the
  chosen personality (`config/personalities/*.md`, the owner's own in `personalities/`), built by
  `alveus/personality.py`. Rules go in the instructions, manner in a personality; shipped personality
  files are never written by the GUI (edits become copies in `personalities/`).
- The confirmation gate is in the agent (`Agent._execute`), not the model: tools marked destructive
  always ask unless listed in `tools.no_confirm`. Silence is `{"ok": False, "reason": "no_answer"}`.
- To test the GUI, run a text-only instance on port 8799 with `ALVEUS_LOCAL_CONFIG` pointing at a
  copy of `local.yaml` and **`INVOCATION_ID` unset** (otherwise its "Save & restart" restarts the real
  systemd services), and drive headless Chrome over DevTools; close each tab you open.
- Docs are part of the deliverable: update `docs/*.md`, rebuild the handbook, commit.

## Traps already hit (details in docs/troubleshooting.md)

- Bonsai GGUFs need the fork's **prism** branch; `master` fails with `invalid ggml type 142`.
- Moving a cmake build dir breaks RPATH; build with `-DCMAKE_BUILD_RPATH_USE_ORIGIN=ON`
  (`scripts/build_llama.sh` does).
- conda's PortAudio cannot open PipeWire-held devices → audio goes through `pw-record`/`pw-play`.
- `mcp` ≥ 2 renamed FastMCP → `mcp_servers/common.py` shim; tool schema fields are snake_case.
- openai SDK + httpx2 streaming misbehaves at close → LLM streaming uses plain `httpx` SSE.
- Chatterbox crashes on text with no pronounceable characters (emoji-only fragments) →
  `speakable()`/`has_speech()` filtering and per-sentence try/except.
- A wrong `voice_ref` path used to silence all speech; now falls back to the built-in voice with a
  `tts_warning` in `/health` and a red toast in the GUI.
- `hf download --include "*.gguf"` on the Bonsai repos pulls 54 GB F16 files; use exact names.
- livekit-wakeword pins newer numpy/onnxruntime → keep it in its own env (`scripts/train_wakeword.sh`).
- Never put `After=default.target` on a unit that is `WantedBy=default.target`: it is an ordering
  cycle and systemd silently drops the assistant's start job at login (fixed 2026-09-09).
- `pkill -f PATTERN` killed this session's shell a third time (exit 144) even with a `[3]` regex trick:
  the harness wraps commands in `bash -c '…'`, so the pattern is in the parent's cmdline too. Kill by
  pid from `ps -eo pid,args | awk` filtered on the executable path.
- Wake-word training (`scripts/train_wakeword.sh`) needs ~25 GB free the first time, and its trainer
  shares the GPU with the running services (24 GB was 97 % full); Whisper OOMed in a side script
  meanwhile. The SC-GN01 speaker→own-mic path records silence, so loopback tests do not work here;
  the owner tests wake words by voice.
- Kokoro is English-only: CJK text is spoken as "Chinese letter …". Chatterbox multilingual speaks it.
- In `mode: both`, every consumer of microphone frames must also feed the openWakeWord model
  (`_record_utterance(watch_wake=True)`); a loop that swallows frames silently disables the wake word.
- If nothing reacts at all, record from the mic first (`pw-record` + peak level); the SC-GN01 has a
  hardware mute button and no software capture control, so `wpctl` looks fine while it delivers silence.
- The `alveus.service` unit must not block on the LLM; the GUI has to stay reachable to fix things.
- uvicorn captures SIGTERM for itself, so `systemctl stop` used to hang until SIGKILL (90 s);
  `cli.talk` now owns the signal handlers and `serve()` disables uvicorn's. `TimeoutStopSec=15`.
- `alveus/web/index.html` contains intentional NUL bytes (markdown placeholders), so `file` calls it
  "data", plain `grep` skips it (use `grep -a`) and some editors choke; patch it byte-safely.
- `google-chrome --headless --dump-dom` dumps before the GUI's async code runs (and
  `--virtual-time-budget` hangs on the `/events` stream). To check the rendered GUI, drive headless
  Chrome over the DevTools protocol (`--remote-debugging-port`, Node 22's built-in WebSocket,
  `Runtime.evaluate` after a few seconds) against a text-only test instance on another port.
- qwen-tts pins transformers 4.57 and breaks on 5.x (`check_model_inputs`): it runs only in its worker
  process with `.venv-qwen3tts`; never install it into the alveus env. The root disk has ~12 GB free:
  put model weights on `/mnt/data` (the Qwen weights are there).
- The snap `ffmpeg` (`/snap/bin/ffmpeg`) cannot read `/tmp` (snap confinement: "No such file");
  use the conda env's `~/miniconda3/envs/alveus/bin/ffmpeg`.
- Anything that drains the speaker queue must keep the `None` end marker (`StreamSpeaker.abort`);
  dropping it hung every reply stopped after generation had finished. `/debug/tasks` finds such hangs.

## The owner

Charles (they/them unless told otherwise), a neuroscience researcher comfortable with conda, systemd
and Python, not interested in boilerplate. Preferences shown so far: short direct answers to short
questions; make decisions swappable via config; plain-language explanations in the GUI; the
ultraviolet/indigo visual theme (Chakra Petch + IBM Plex) for GUI and handbook; offline HTML docs
rather than hosted artifacts; the assistant must be installable on another Linux/CUDA machine with
`./install.sh`. They test by talking to it and by using the GUI, and report symptoms rather than
causes — check `journalctl --user -u alveus` first.

## Next items

The roadmap and the history live in **`docs/devlog.md`** (Plans section at the top; add an entry
there for every working session, newest first). Current order: (1) conversations and memory,
(2) image generation follow-ups (ComfyUI is wired in; next: a real instruction editor such as
Qwen-Image-Edit, picture upload in the GUI, vision input to see the result), (3) vision input and video, (4) interrupt by speech (echo cancellation first),
(5) wake-word tuning for the owner's voice. Update the dev log, not this file, when priorities change.
