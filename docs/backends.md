# Backends: LLM, STT, TTS, audio

Every stage of the pipeline is a backend chosen in configuration. This page lists what exists,
how each performed on the reference machine (RTX 4090), how to switch, and how to add more.

## LLM

### Interface

`alveus/llm/base.py`: `LLMBackend.stream(messages, tools, thinking) -> AsyncIterator[LLMEvent]`
with events `reasoning`, `content`, `tool_call`, `done`, plus `health()`.

The agent keeps one provider-neutral conversation (OpenAI-style `system`/`user`/`assistant`/`tool`
messages) and every adapter translates it to its own wire format, so a conversation can move
between providers. `done` carries a normalized `finish_reason` (`stop`, `tool_calls`, `length`,
`refusal`), usage (`prompt_tokens`, `completion_tokens`, `cached_tokens`) and optional `replay`
data: the provider's own record of that message (Claude's signed thinking blocks, OpenAI's
encrypted reasoning items). The agent stores it as `_replay` on the assistant message and only
the adapter of the same provider sends it back, verbatim; everyone else rebuilds the message from
its text and tool calls. Failures raise `LLMError`, whose short message is spoken as is
("DeepSeek rejected the API key").

### Profiles, providers, protocols

A profile (`llm.profiles.<name>`) is a **provider** plus a **model**. The provider preset in
`alveus/llm/providers.py` supplies the protocol, address, API-key variable and quirks; the profile
can override any of it. Resolution: preset < llm-level defaults (`temperature`, `top_p`,
`max_tokens`, `effort`, `max_tool_rounds`) < the profile. Parameters a provider rejects (its
`unsupported` list, e.g. `temperature` for Claude and OpenAI) are dropped unless the profile itself
sets them. A provider name that is not a preset works when the profile gives `api` and `base_url`.

| provider | protocol (`api`) | address | key variable | notes |
|---|---|---|---|---|
| `llama_server` | `openai_chat` | `127.0.0.1:8080/v1` | — | started by `alveus-llm` from the profile's `serve:` |
| `vllm` | `openai_chat` | `127.0.0.1:8000/v1` | — | |
| `ollama` | `openai_chat` | `127.0.0.1:11434/v1` | — | |
| `openai_compat` | `openai_chat` | your `base_url` | your `api_key_env` | LM Studio, SGLang, Groq, Together, Mistral, … |
| `openai` | `openai_responses` | `api.openai.com/v1` | `OPENAI_API_KEY` | current OpenAI models call tools only through the Responses API |
| `anthropic` | `anthropic_messages` | SDK default | `ANTHROPIC_API_KEY` | official `anthropic` SDK |
| `deepseek` | `openai_chat` | `api.deepseek.com` | `DEEPSEEK_API_KEY` | reasoning sent back (DeepSeek requires it once tools are used) |
| `openrouter` | `openai_chat` | `openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | many vendors' models behind one key |

### `openai_chat` — Chat Completions (`alveus/llm/openai_compat.py`)

Speaks `/chat/completions` with `stream: true` over server-sent events using plain `httpx` (no
vendor SDK), accumulates streamed tool-call fragments by index, repairs truncated JSON arguments,
and reads `reasoning_content` (llama.cpp, DeepSeek) or `reasoning` (vLLM, OpenRouter). Verified
with llama-server. Preset knobs: `thinking_param` (how `thinking: true|false` is sent:
`chat_template_kwargs.enable_thinking` for Qwen-style templates, `thinking: {type}` for DeepSeek,
or not at all), `reasoning_replay: all` (send each assistant message's reasoning back as
`reasoning_content`), `max_tokens_field`. `effort` becomes `reasoning_effort`. Connection
failures and 429/5xx are retried twice before any output arrives.

### `openai_responses` — OpenAI Responses (`alveus/llm/openai_responses.py`)

`/responses` with `store: false`: OpenAI keeps no copy, and every turn sends the whole
conversation as `input` items (`function_call` / `function_call_output` for tools). Reasoning
items come back with `encrypted_content` and are replayed verbatim (same model only), so the
model keeps its reasoning across tool calls. `effort` → `reasoning.effort`, reasoning summaries
(`reasoning_summary: auto`) are shown in the GUI, `max_tokens` → `max_output_tokens`.

### `anthropic_messages` — Claude (`alveus/llm/anthropic_messages.py`)

Uses the official `anthropic` SDK (`client.messages.stream`). System messages become the
top-level `system`, tool calls `tool_use` blocks, consecutive tool results one `user` message of
`tool_result` blocks. Thinking is adaptive (`thinking: {type: adaptive, display: summarized}`) and
its depth is set with `effort` (`output_config.effort`; Claude Opus 5.5 always thinks and defaults
to `medium`). Claude's thinking blocks are signed and bound to the conversation that produced
them, so each assistant message is replayed exactly as returned; when the agent trims old turns
it drops that data (it is marked `prefix_bound`) and the message is rebuilt without thinking,
which keeps the request valid. Top-level `cache_control` caches tools, system prompt and history,
so a long conversation is mostly billed at the cache-read rate. `fallbacks: default` (server-side
fallback, beta `server-side-fallback-2026-07-01`) lets Anthropic re-run a request its safety
classifier declined on another model instead of failing; a model that does not take the
parameter gets it removed automatically. A refusal ends the turn with "The model declined to
answer that request". Without a key in Alveus' store, the SDK's own credential lookup
(`ANTHROPIC_API_KEY`, `ant auth login`) applies.

### Shipped profiles

| profile | provider | model | notes |
|---|---|---|---|
| `bonsai-1bit` (default) | `llama_server` | `Bonsai-27B-Q1_0.gguf`, 3.8 GB | ~90 % of FP16 quality, 27B params, Qwen3.6 base, 262k ctx, native tool calling + thinking. ~60–95 tok/s |
| `bonsai-ternary` | `llama_server` | `Ternary-Bonsai-27B-PQ2_0.gguf`, 7.2 GB | ~95 %; better agentic/tool scores (BFCL, τ²-bench); same server flags |
| `qwen-local` | `llama_server` | `Qwen3.8-27B-Q4_K_M.gguf` (not downloaded) | template for any standard GGUF; put the file at `serve.model_path` first |
| `claude` | `anthropic` | `claude-opus-5-5` | `max_tokens: 16000` (thinking counts against it) |
| `chatgpt` | `openai` | `gpt-6.1-sol` | Responses API, `max_tokens: 16000` |
| `deepseek` | `deepseek` | `deepseek-v4-pro` | thinking on by default; `deepseek-flash` is the cheaper model |

The Bonsai files need the **PrismML fork of llama.cpp**, specifically its `prism` branch, for the
custom kernels (`Q1_0` = type 41 is also on the fork's master, but `PQ2_0` = type 142 only exists
on `prism`; upstream llama.cpp only runs the `Q2_g64` ternary variant). `scripts/build_llama.sh`
clones/checks out `prism` and builds. A model architecture newer than the fork may need an
upstream llama.cpp build; give that profile its own `serve.command`. Switching profiles in the GUI
runs a check first and refuses the switch if the binary cannot read the file (local) or the
provider does not accept the key and model (cloud).

Cloud latency and cost were not measured on the reference machine. Requirements for a good voice
experience are the same everywhere: tool calling, streaming, and a short time to the first
sentence; lower `effort` shortens the thinking before the reply.

### API keys

Cloud providers read their key from the environment or from `~/.config/alveus/secrets.env`
(`ALVEUS_SECRETS` overrides the path): a `NAME=value` file outside the repository, mode 600.
Set keys in the GUI (Settings → Language model → API keys; values are write-only) or with
`alveus llm key ANTHROPIC_API_KEY`. Keys are read per request, so a new key works without a
restart. They are never written to `config/*.yaml`, never exported to `os.environ`, and API-key
variables are removed from the environment of the tool servers (the shell tool could print them),
except for servers with `inherit_api_keys: true` (the coder, so opencode can sign in).

With a cloud profile, everything in the conversation is sent to that provider: your transcribed
words, the system prompt, and whatever tools return (file contents, command output, web pages).
Speech recognition and synthesis stay local.

### Switching

GUI: Settings → Language model → Model profile, then save (check, then restart of both services).
The choice is stored as `llm.profile` in `config/local.yaml`, so every later start, including after
a reboot, uses the model chosen last. Choosing a cloud profile makes `alveus llm serve` exit at once,
so `alveus-llm` stops and the GPU is free (ComfyUI, bigger speech models). On top of that the
assistant checks the unit every time it starts (`alveus/llm/service.py`, `llm.manage_local_server`):
it stops a local server that a cloud profile does not need, starts one a local profile needs, and
restarts it when it serves a different model, so a switch through the YAML editor or a hand edit
followed by `systemctl --user restart alveus` ends in the same state. CLI: `alveus llm profiles` (provider, local/cloud, key
or weights present), `alveus llm test --profile claude` (one request), `alveus chat --profile
deepseek` (text REPL with tools), `ALVEUS_LLM_PROFILE=chatgpt alveus talk`.

### Adding a profile, provider or protocol

- **Another model on a known provider:** a new profile with `provider` and `model`.
- **Another OpenAI-compatible service:** `provider: openai_compat`, `base_url`, `model`,
  `api_key_env` (its key then appears in the GUI's key list); or add a preset to `PROVIDERS`.
- **Another protocol:** one file under `alveus/llm/` implementing `stream()` / `health()` and the
  conversion from the neutral messages, registered in `make_llm()` (`alveus/llm/__init__.py`) and
  `APIS` (`providers.py`). The three existing adapters are 190–270 lines each.

## Speech-to-text

### Interface

`alveus/stt/base.py`: `load()` and `transcribe(float32_audio, sample_rate) -> str`.

| backend | engine | VRAM | latency (4090) | strengths | notes |
|---|---|---|---|---|---|
| `faster_whisper` (default) | CTranslate2 Whisper `large-v3-turbo`, fp16 | ~1.5 GB | 0.06–0.2 s per utterance | robust, multilingual, punctuation | imports torch first so ctranslate2 finds cuDNN 9 |
| `parakeet` | NVIDIA Parakeet TDT 0.6B v3 via onnx-asr | ~1 GB (CPU works too) | ~0.3 s | very fast, 25 European languages | first load downloads ~2.5 GB; names slightly less accurate ("Oria") |
| `openai_http` | any `/v1/audio/transcriptions` server | — | network | reuse whisper.cpp server, speaches, etc. | |

Switch: `stt.backend: parakeet` or `ALVEUS_STT_BACKEND=parakeet`. Test: `alveus stt test`.

Both local engines run on whole utterances (not streaming); with the VAD-based segmenting the
transcript is ready ~0.1–0.3 s after you stop speaking, which is what gates the response time.

## Text-to-speech

### Interface

`alveus/tts/base.py`: `load()`, `synthesize(text) -> float32 audio`, `sample_rate`, `voices()`.

| backend | engine | VRAM | speed (4090) | strengths | notes |
|---|---|---|---|---|---|
| `kokoro` (default) | Kokoro-82M (PyTorch) | ~0.6 GB | ~10× faster than real time after warm-up | crisp, 28 voices, tiny | no cloning; sample rate 24 kHz |
| `chatterbox` | Resemble Chatterbox: `turbo` (English), `standard` (English), `multilingual` (23 languages) | 3–4 GB | ~0.2× real time (4 s of speech in 0.85 s) | most natural, zero-shot voice cloning from a WAV; multilingual speaks zh, ja, ko, de, fr, es, it, pt, ru, ar, hi… | multilingual picks the language per sentence (`tts.chatterbox.language: auto`): script detection for CJK/Cyrillic/Arabic/…, `langdetect` for Latin text, `fallback_language` otherwise |
| `openai_http` | any `/v1/audio/speech` server | — | network | Kokoro-FastAPI, openedai-speech, … | |

Switch: `tts.backend: chatterbox` (+ `chatterbox.voice_ref: ~/voices/me.wav` for cloning; `chatterbox.model:
multilingual` to speak other languages). For a bilingual conversation also clear
`stt.faster_whisper.language` so Whisper auto-detects what you say; the LLM answers in the language
you used, and the streaming splitter understands Chinese/Japanese sentence punctuation (。！？).
Test: `alveus tts say "Hello there"`. The chosen voice's gender decides the spoken name
(`tts.voice_gender`, auto from Kokoro voice prefixes).

Streaming: text is split into sentences (`SentenceBuffer`, min 24 chars, abbreviation- and
decimal-aware) and each sentence is synthesized while the model continues generating, so
time-to-first-word ≈ LLM thinking time + first sentence generation + ~0.2 s synthesis.

## Voice activity & wake word

- **Silero VAD** (`silero-vad` PyTorch package) on 32 ms frames, CPU. Threshold `audio.vad.threshold`.
- **openWakeWord 0.6** on ONNX runtime (the `tflite-runtime` dependency is dropped because it has
  no Python 3.12 wheels). Feeds 80 ms int16 chunks; pretrained and custom models supported.
- **Name detection** – no model; uses the STT transcript. See [wake-words.md](wake-words.md).

## Audio I/O

| backend | how | when |
|---|---|---|
| `pipewire` (auto-selected when available) | `pw-record`/`pw-play` subprocesses, s16 in / f32 out, 32–64 ms latency | any PipeWire desktop (Ubuntu ≥ 22.10, Fedora, Arch…) |
| `sounddevice` | PortAudio streams | macOS, PulseAudio-only or headless ALSA setups; needs a PortAudio that can open the device |

Select devices with `audio.input_device` / `output_device` (PipeWire node name or serial from
`wpctl status`; sounddevice index or name substring). Playback is a queue in a background thread,
interruptible via `AudioOut.stop()` (hotkey barge-in, `/stop`).

## Optional server-side variants

Instead of in-process STT/TTS you can run them as separate services and point the `openai_http`
backends at them — useful if you want the speech models shared with other apps, or on another
machine:

- STT: `speaches` (faster-whisper server), whisper.cpp `server`, Parakeet FastAPI wrappers.
- TTS: `Kokoro-FastAPI` (port 8880), `Chatterbox-TTS-Server`, `openedai-speech`.
