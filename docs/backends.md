# Backends: LLM, STT, TTS, audio

Every stage of the pipeline is a backend chosen in configuration. This page lists what exists,
how each performed on the reference machine (RTX 4090), how to switch, and how to add more.

## LLM

### Interface

`alveus/llm/base.py`: `LLMBackend.stream(messages, tools, thinking) -> AsyncIterator[LLMEvent]`
with events `reasoning`, `content`, `tool_call`, `done`, plus `health()`.

### `openai` — any OpenAI-compatible chat endpoint (`alveus/llm/openai_compat.py`)

Speaks `/v1/chat/completions` with `stream: true` over server-sent events using plain `httpx`
(no vendor SDK), accumulates streamed tool-call fragments by index, repairs truncated JSON
arguments, and reads `reasoning_content` (llama.cpp) or `reasoning` (other servers). Verified
with llama-server; also works with vLLM, SGLang, Ollama (`/v1`), LM Studio, LocalAI, and hosted
APIs (set `api_key`).

### Shipped profiles

| profile | weights | size | quality vs FP16 | notes |
|---|---|---|---|---|
| `bonsai-1bit` (default) | `Bonsai-27B-Q1_0.gguf` | 3.8 GB | ~90 % | 27B params, Qwen3.6 base, 262k ctx, native tool calling + thinking. ~60–95 tok/s |
| `bonsai-ternary` | `Ternary-Bonsai-27B-PQ2_0.gguf` | 7.2 GB | ~95 % | better agentic/tool scores (BFCL, τ²-bench); same server flags |

Both need the **PrismML fork of llama.cpp** for their custom kernels (upstream llama.cpp only runs
the `Q2_g64` ternary variant). The fork is built by `scripts/build_llama.sh`.

### Swapping the LLM

Add a profile; nothing else changes:

```yaml
llm:
  profile: qwen-vllm
  profiles:
    qwen-vllm:
      backend: openai
      base_url: http://127.0.0.1:8000/v1
      api_key: local
      model: Qwen/Qwen3-32B-AWQ
      reasoning: true
      thinking: false          # optional: faster replies, weaker tool choice
      extra_body: { top_k: 20 }
      # optional, lets `alveus llm serve` start it:
      # serve: { command: vllm, model_path: Qwen/Qwen3-32B-AWQ, args: [serve, --port, "8000"] }
```

Requirements for a good voice experience: tool calling (OpenAI `tools` format), streaming, and
≥ 30 tok/s. For remote APIs, remember that requests (including tool results such as file
contents) leave the machine.

### Adding a non-OpenAI backend

Implement the protocol in a new file under `alveus/llm/`, register it in `alveus/llm/__init__.py`
(`make_llm`), and name it in the profile's `backend`. About 100 lines.

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
| `chatterbox` | Resemble Chatterbox Turbo / standard | 3–4 GB | ~0.15 s to first audio | most natural, zero-shot voice cloning from a WAV | heavier install; installed and importable, not yet exercised in a session |
| `openai_http` | any `/v1/audio/speech` server | — | network | Kokoro-FastAPI, openedai-speech, … | |

Switch: `tts.backend: chatterbox` (+ `chatterbox.voice_ref: ~/voices/me.wav` for cloning).
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
