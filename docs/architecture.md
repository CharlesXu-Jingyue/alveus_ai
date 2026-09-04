# Architecture

## Component diagram

```
                     ┌──────────────────────────── alveus talk (one process) ────────────────────────────┐
                     │                                                                                   │
 PipeWire            │  AudioIn ──► 32 ms frames ──► Silero VAD ──┐                                      │
 pw-record ─────────►│   (thread)                                 ├─► activation logic (names / oww /    │
                     │                        openWakeWord ───────┘   hotkey / follow-up window)          │
 pynput hotkey ─────►│  Trigger flag                                        │                             │
 POST /trigger ─────►│                                                      ▼                             │
                     │                                     utterance (float32 16 kHz)                    │
                     │                                                      │                             │
                     │                                             STT backend (thread pool)             │
                     │                                                      │ text                        │
                     │                                              NameMatcher (fuzzy)                  │
                     │                                                      │ command                     │
                     │   ┌──────────────────────────── Agent.run() ─────────┴──────────────────────┐     │
                     │   │  system prompt + history ──► LLMBackend.stream() ──► events              │     │
                     │   │        ▲                        (httpx SSE)          │                   │     │
                     │   │        │ tool results                                │ tool_calls        │     │
                     │   │   ToolHub.call() ◄────────────────────────────────────┘                   │     │
                     │   │        │  stdio / HTTP (MCP)                                              │     │
                     │   └────────┼──────────────────────────────────────────────────────────────────┘     │
                     │            │                            content deltas                              │
                     │            │                                 │                                      │
                     │            │                        SentenceBuffer ──► speakable() ──► TTS backend  │
                     │            │                                                               │        │
 PipeWire            │            │                                          AudioOut queue (thread)       │
 pw-play  ◄──────────┤            │                                                                        │
                     │   FastAPI (uvicorn, :8765) ── /chat /speak /transcribe /trigger /stop /tools        │
                     └────────────┼────────────────────────────────────────────────────────────────────────┘
                                  ▼
        ┌───────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────────┐
        │ files     │ │ desktop  │ │ system   │ │ web      │ │ coder → opencode run │   MCP server processes
        └───────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────────────────┘
                                                                        │
                                                    llama-server (:8080, systemd alveus-llm) ◄── LLM HTTP
```

Two long-running processes matter: **`alveus-llm`** (llama-server holding the model in VRAM) and
**`alveus`** (`alveus talk`: audio loop, agent, speech models, API, and the five MCP child processes
it spawns over stdio).

## Packages

| path | responsibility |
|---|---|
| `alveus/config.py` | Layered YAML loading, `${VAR}`/`~` expansion, `DotDict`, `llm_profile()` |
| `alveus/llm/` | `LLMBackend` protocol + `OpenAICompatLLM` (SSE streaming, tool-call accumulation, reasoning separation) |
| `alveus/stt/` | `STTBackend` protocol + faster-whisper, Parakeet (onnx-asr), OpenAI-HTTP |
| `alveus/tts/` | `TTSBackend` protocol + Kokoro, Chatterbox, OpenAI-HTTP |
| `alveus/audio/backend.py` | `AudioIn`/`AudioOut` with PipeWire (subprocess) and sounddevice implementations |
| `alveus/audio/vad.py` | Silero VAD on 512-sample frames |
| `alveus/audio/wakeword.py` | openWakeWord wrapper (ONNX runtime, 1280-sample chunks) |
| `alveus/audio/names.py` | `NameMatcher`: fuzzy detection of Alveus/Aurea in a transcript |
| `alveus/audio/hotkey.py` | pynput global hotkey, `Trigger` flag |
| `alveus/audio/chimes.py` | synthesized listen/error chimes |
| `alveus/agent/mcp_client.py` | `ToolHub`: connects MCP servers, namespaces tools, executes calls |
| `alveus/agent/loop.py` | `Agent`: system prompt, history, tool loop, destructive-action gate, `active_names()` |
| `alveus/agent/sentences.py` | `SentenceBuffer` for streaming TTS, `speakable()` markdown stripper |
| `alveus/voice.py` | `VoiceAssistant`: the state machine tying everything together |
| `alveus/api.py` | FastAPI app + `HeadlessAssistant` (agent without microphone) |
| `alveus/cli.py` | Typer CLI (`alveus …`) |
| `mcp_servers/` | Built-in MCP servers (one file each) + `common.py` helpers/compat |

## Data flow of one voice turn

1. **Capture.** `PipeWireIn` runs `pw-record --rate 16000 --channels 1 --format s16 -` and a reader
   thread slices stdout into 512-sample float32 frames (32 ms) on a bounded queue (oldest dropped
   if the consumer stalls).
2. **Activation.** The main loop pulls frames. Each frame is scored by Silero VAD and, in `oww`
   or `both` mode, by openWakeWord. The `Trigger` flag is set by the hotkey thread or the API.
3. **Segment recording.** When speech is detected (or the trigger fires), `_record_utterance`
   collects frames until `end_silence_ms` of non-speech, `max_utterance_s`, or a second hotkey
   press. Segments shorter than `min_speech_ms` of speech are discarded.
4. **Transcription.** The segment goes to `STTBackend.transcribe()` in a worker thread. Known
   Whisper hallucinations on near-silence ("Thank you.") are dropped.
5. **Name matching** (names mode). `NameMatcher.match()` checks the first two words (and their
   concatenation) and the last word against the names and aliases with `difflib` similarity
   ≥ 0.78. Leading fillers ("hey", "ok", "um") are stripped. Result: *(addressed, remaining
   command)*. Not addressed → the segment is ignored. Addressed with no command → chime and
   record the next utterance. Addressed with a command → proceed directly.
6. **Agent loop.** `Agent.run(text)` appends the user message, then repeats up to
   `llm.max_tool_rounds` times: build `[system] + history`, stream the LLM, forward `content`
   deltas, collect `tool_call`s. If tool calls were made, each is executed via `ToolHub`
   (after the destructive-action gate), results are appended as `role: tool` messages, and the
   loop continues. When the model answers without tools, the turn ends.
7. **Speech output.** `content` deltas feed `SentenceBuffer`; each complete sentence is
   markdown-stripped by `speakable()`, synthesized by the TTS backend in a worker thread, and
   pushed to `AudioOut`, whose thread streams float32 PCM to `pw-play`. Because synthesis of
   sentence *n+1* overlaps playback of sentence *n* and generation of the rest, the first words
   are heard while the model is still writing.
8. **Follow-up.** After playback the loop opens a `follow_up_window_s` window during which any
   speech is treated as addressed.

## The voice state machine

```
            ┌────────────────────────────────────────────────────────────────┐
            │                                                                │
            ▼    name+command / trigger / follow-up speech                   │
         IDLE ────────────────────────────────────────────► THINKING ──► SPEAKING
            │                                                  ▲               │
            │ name only / hotkey / oww phrase                   │ transcript    │ playback done
            ▼                                                  │               │
        LISTENING (chime, record until silence) ───────────────┘               │
            │ nothing heard within 6 s                                         │
            └──────────────────────────────► IDLE ◄────────────────────────────┘
                                             (follow-up window open for N s)
```

`on_state` callbacks let the CLI print state changes; the API's `/health` reports the current state.

## Concurrency model

- The main coroutine runs the state machine on asyncio.
- Blocking work (audio reads, STT, TTS, VAD reset) runs in a 3-worker `ThreadPoolExecutor`.
- `AudioIn` and `AudioOut` each own one background thread plus a `pw-record`/`pw-play` child.
- LLM streaming is async (httpx). MCP servers are child processes; `ToolHub` talks to them
  through the `mcp` client library's async stdio transport, all inside one `AsyncExitStack`.
- The FastAPI server runs in the same event loop (uvicorn `Server.serve()`), so `/chat` with
  `speak: true` shares the loaded models and the speaker queue with the voice loop.

## Prompting and model interface

- The system prompt is `config/persona.md` rendered with `{name}`, `{other_name}`,
  `{user_name}`, `{date}`, `{hostname}`, `{os}`, plus a line listing available tool groups.
- Tools are presented in OpenAI function-calling format, names namespaced `server__tool`
  (`system__gpu_status`). llama-server's `--jinja` renders Bonsai's Qwen3.6 chat template, which
  natively supports tools and thinking. `--reasoning-format deepseek` moves thinking into
  `reasoning_content`, which Alveus never speaks.
- History keeps the last `assistant.max_history_turns` user turns (and everything after them,
  including tool messages).
- `thinking: true|false` on a profile forces `chat_template_kwargs.enable_thinking`; unset
  keeps the model default (thinking on for Bonsai). Thinking costs ~1 s per turn but improves
  tool selection.

## Safety model

- **Destructive gate.** A tool call is confirmed before execution if the tool carries
  `destructive_hint` (delete_path, move_path, close_window, kill_process, control_service,
  power) or if a `run_command` command matches `_DESTRUCTIVE_SHELL` in `agent/loop.py`
  (`rm`, `kill`, `shutdown`, `mkfs`, `dd`, `git push --force`, `chmod -R`, …). In voice mode the
  assistant asks aloud and listens for yes/no; in `alveus chat` it prompts on the terminal;
  through the bare `/chat` API there is no confirmer, so destructive calls are refused.
  Disable with `tools.confirm_destructive: false`.
- **Filesystem scope.** The files server only touches paths under `ALVEUS_FS_ROOTS`
  (default `~`).
- **Network exposure.** llama-server and the API bind to 127.0.0.1. Nothing is exposed on the LAN
  unless you change `api.host` or the server args.
- **Prompt injection.** Web page content and file contents returned by tools are model input.
  The persona asks for confirmation before irreversible actions, and the gate enforces it for
  the risky tool set regardless of what the model "decides".

## Portability decisions

- All machine-specific paths live in `config/local.yaml` under `env:` (`ALVEUS_MODELS`,
  `ALVEUS_LLAMA_SERVER`), written by `install.sh`. The repo root is discovered from
  `alveus/config.py`'s location, so the checkout can live anywhere.
- systemd unit templates (`systemd/*.service.in`) are rendered per machine by
  `scripts/install_services.sh`, substituting the Python interpreter and paths.
- Audio uses PipeWire's CLI tools rather than PortAudio because conda-forge's PortAudio cannot
  open ALSA devices that PipeWire already holds; PortAudio remains as the fallback for
  non-PipeWire systems.
