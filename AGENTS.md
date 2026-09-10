# AGENTS.md — orientation for a new session working on Alveus

Read this first. It tells you what the project is, where everything lives, how to run and verify
it, what the owner cares about, and the traps that have already cost time. Written 2026-09-09.

## What this is

Alveus (also called **Aurea** when its voice is female) is a fully local, voice-driven AI
assistant for the owner's Linux workstation. Speech in → local LLM with tools → speech out, plus a
browser GUI. Nothing leaves the machine except the web tools. Repo: `~/local/repo/alveus-ai`,
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
| models (`ALVEUS_MODELS`) | `~/local/model/bonsai/Bonsai-27B-Q1_0.gguf`, `~/local/model/bonsai-ternary/Ternary-Bonsai-27B-PQ2_0.gguf` |
| llama.cpp (PrismML fork, **prism** branch, relocatable build) | `~/local/lib/llama.cpp-bonsai/build/bin/llama-server` |
| voice samples for cloning | `~/local/data/alveus-ai/voices/` (`tts.voices_dir`) |
| systemd user units | `~/.config/systemd/user/alveus-llm.service`, `alveus.service` (rendered from `systemd/*.in` by `scripts/install_services.sh`) |
| logs | `journalctl --user -u alveus -f`, `logs/alveus.log` |
| GUI + API | http://127.0.0.1:8765/ (served by the `alveus` service), API docs at `/docs`, handbook at `/handbook` |
| LLM server | http://127.0.0.1:8080/v1 (OpenAI-compatible) |
| opencode config (coder tool) | `~/.config/opencode/opencode.jsonc`, provider `bonsai` |

Hardware: RTX 4090 24 GB, i9-13900K, 62 GB RAM, Ubuntu 24.04, GNOME on X11, PipeWire audio
(motherboard USB audio + Panasonic SC-GN01 speaker/mic).

## Current configuration (check `config/local.yaml`, it may have moved on)

LLM profile `bonsai-ternary` (Ternary-Bonsai-27B, ~89 tok/s). STT faster-whisper large-v3-turbo,
language fixed to `en` unless the owner cleared it. TTS **Chatterbox multilingual** with the cloned
sample `m_demo_charles.wav`; voice gender `auto` (inferred from the `m_`/`f_` file prefix) → the
assistant currently calls itself Alveus. Activation: names mode ("Alveus"/"Aurea" in the sentence)
plus hotkey ctrl+alt+space. Both services enabled at login.

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

## Conventions

- One backend per file under `alveus/llm|stt|tts/`, registered in that package's `__init__`
  factory; heavy imports happen inside `load()`.
- MCP servers: `from .common import FastMCP, annot, j, run`; return JSON strings; mark irreversible
  tools `annot(destructive=True)` — that is what triggers the spoken/GUI confirmation.
- Config patch semantics (`alveus/config.py`): a `null` leaf stores an explicit null (e.g. language
  auto-detect); `{"$unset": true}` removes the machine override. The GUI relies on this.
- GUI settings are declared in the `FIELDS` array in `alveus/web/index.html` (`when:` makes a field
  depend on another; `nullable:` lets empty mean null; `t:'file'` is the voices picker). Write
  field hints in plain language; the owner reads them and asks when they are vague.
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
- The `alveus.service` unit must not block on the LLM; the GUI has to stay reachable to fix things.
- uvicorn captures SIGTERM for itself, so `systemctl stop` used to hang until SIGKILL (90 s);
  `cli.talk` now owns the signal handlers and `serve()` disables uvicorn's. `TimeoutStopSec=15`.
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

## Next items (agreed with the owner on 2026-09-09, in priority order)

1. **Chat scrolling in the GUI**: generation forces the log to the bottom (`scrollBottom()` on every
   event in `alveus/web/index.html`). Only auto-scroll while the user is already at the bottom; when
   they scroll up, stop following; when they scroll back down to the bottom, follow again.
2. **Custom wake-word models for "Alveus" and "Aurea"**: names mode has too many false negatives
   (uncommon words for Whisper). Train openWakeWord models with `scripts/train_wakeword.sh`
   (livekit-wakeword in its own env; docs/wake-words.md), put them under `$ALVEUS_MODELS/wakeword/`,
   support a list of models in `alveus/audio/wakeword.py`, run `activation.wake_word.mode: both`,
   tune with `alveus wakeword-test`.
3. **Conversations and memory**: persist conversations (list, resume, search), summarize long ones,
   and a memory store the agent can read and write across restarts (facts, preferences). Likely an
   MCP server plus a sidebar in the GUI; today history lives only in `Agent.history` in memory.
4. **Image and video models**: vision input (Bonsai `mmproj` via llama-server `--mmproj`,
   screenshots, camera), image generation, video understanding and generation, each a pluggable
   backend like STT/TTS.
5. **Interrupt by speech** (agreed 2026-09-09): (1) PipeWire echo cancellation (`module-echo-cancel`)
so the mic no longer hears the assistant's own voice; select the cancelled source as
`audio.input_device`; verify by recording while it speaks. (2) Name-triggered barge-in: while
speaking, run VAD on the cleaned mic, transcribe short segments with the loaded STT, and treat a
name match like the Listen button (interrupt, then listen). (3) Replace the transcription step with
the custom wake-word models once trained; optionally allow any-speech interruption.

Other ideas: timers/reminders (GNOME Clocks is not scriptable; use `systemd-run --user --on-active`
or an in-process timer that also calls `/speak`); Home Assistant; speaker identification.
