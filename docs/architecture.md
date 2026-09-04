# Architecture notes

## Turn lifecycle (`alveus/voice.py`)

1. **IDLE** – frames (32 ms, 16 kHz) stream from PipeWire. Each frame goes to Silero VAD and,
   in `oww` mode, to openWakeWord. The hotkey / `POST /trigger` set a `Trigger` flag.
2. **Name detection** (`names` mode) – when VAD says speech started, the segment is recorded until
   `end_silence_ms` of quiet, transcribed, and checked by `NameMatcher` (first two words or the last
   word, fuzzy). If addressed with a command in the same breath, the command runs immediately;
   if only the name was said, a chime plays and the next utterance is recorded.
3. **Follow-up window** – for `follow_up_window_s` after a reply, speech is accepted without a name.
4. **THINKING** – `Agent.run()` streams the LLM. Reasoning tokens are dropped, content is split into
   sentences (`SentenceBuffer`) and each sentence is synthesized and queued for playback while the
   model keeps generating. Tool calls are executed through `ToolHub` (MCP) and the loop continues
   until the model answers without tools (max `llm.max_tool_rounds`).
5. **SPEAKING** – playback runs in a background thread; the hotkey (or the wake-word model) can
   interrupt it (barge-in).

## Swappability

* `alveus/llm/base.py` – `LLMBackend.stream(messages, tools) -> LLMEvent*`; one implementation
  (`OpenAICompatLLM`) covers llama-server, vLLM, Ollama, LM Studio, and hosted APIs.
* `alveus/stt/base.py`, `alveus/tts/base.py` – tiny protocols; each backend is one file.
* `alveus/audio/backend.py` – PipeWire (subprocess) or PortAudio.
* MCP servers are separate processes; the agent only sees OpenAI-style tool schemas.

## Safety

* Tools with `destructive_hint` (and shell commands matching a danger regex) trigger a spoken
  confirmation before running (`tools.confirm_destructive`).
* The files server only touches paths under `ALVEUS_FS_ROOTS`.
* All services bind to 127.0.0.1.
