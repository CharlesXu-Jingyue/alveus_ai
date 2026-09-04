# Overview

## What Alveus is

Alveus is a personal, "Jarvis-style" AI assistant that runs **entirely on one Linux machine
with an NVIDIA GPU**. You speak to it, it understands, reasons with a local language model,
acts on your computer through tools, and answers out loud. No audio, text, or data leaves the
machine unless a tool you explicitly enabled (web search, page fetch, weather) reaches out to
the internet.

It answers to two names. **Alveus** is the default; when the configured voice is female (the
default Kokoro voice `af_heart` is), it introduces itself as **Aurea**. Both names are always
accepted, both wake it up, and the persona tells the model never to correct you about which
name you used.

## Design goals

1. **Fully local.** LLM inference (llama.cpp), speech-to-text, text-to-speech, voice activity
   detection and wake-word detection all run on the local GPU/CPU.
2. **Every stage swappable.** The LLM, STT engine, TTS engine, audio backend and activation
   method are each selected in one YAML file. Upgrading the model later means adding a
   profile, not rewriting code. Any OpenAI-compatible server (vLLM, Ollama, LM Studio, a
   remote API) is a valid LLM backend.
3. **Real agency, with guard rails.** The model calls tools through the Model Context Protocol
   (MCP): files, shell, GNOME desktop, system status/control, web, and delegation of coding
   work to opencode. Destructive actions are confirmed by voice before they run.
4. **Portable.** `install.sh` reproduces the whole stack on another Linux + CUDA box; nothing
   in the repo depends on this machine's paths.
5. **Small.** ~2,500 lines of Python. Each backend is one short file.

## Capabilities at a glance

| area | examples of what you can say |
|---|---|
| Conversation | "Aurea, what's the date?", "explain what a Mamba layer is in two sentences" |
| System | "what's my GPU temperature?", "how much RAM is free?", "what's using the CPU?", "is the internet up?" |
| Files & shell | "list the files in my repo folder", "find PDFs in Downloads", "search my notes for 'hypothalamus'", "run `df -h`" |
| Desktop | "open Firefox", "set the volume to 30 percent", "mute", "pause the music", "take a screenshot", "dark mode on", "do not disturb", "copy this to the clipboard: …", "lock the screen" |
| Web | "what's the weather in Boston?", "search the web for the latest llama.cpp release", "summarize this page: …" |
| Coding | "in ~/local/repo/foo, add a README explaining the data layout" (delegated to opencode), "what does SAEM/main.py do?" |
| Power / services | "suspend the computer" (asks first), "restart my alveus-llm service" (asks first) |
| Follow-ups | For 8 s after a reply you can continue without saying the name |

See [usage.md](usage.md) for more phrasing and [tools.md](tools.md) for the exact tool list.

## Hardware footprint (measured on this machine: RTX 4090, i9-13900K, 62 GB RAM)

| component | VRAM | load time | latency |
|---|---|---|---|
| Bonsai-27B 1-bit (llama-server, 32k ctx, flash-attn) | ~6.5 GB | ~20 s | ~60–95 tok/s generation, ~190 tok/s prompt |
| faster-whisper large-v3-turbo (fp16) | ~1.5 GB | ~30 s first time (download), ~5 s after | 0.06–0.2 s per utterance |
| Kokoro-82M | ~0.6 GB | ~8 s | ~0.3× real time (1.4 s for 3.4 s of speech, incl. warm-up) |
| Silero VAD | CPU | <1 s | ~1 ms per 32 ms frame |
| openWakeWord (optional) | CPU | <1 s | ~5 ms per 80 ms chunk |
| Parakeet TDT 0.6B v3 (optional) | ~1 GB / CPU | ~35 s first time | ~0.3 s per utterance |
| Chatterbox Turbo (optional) | 3–4 GB | ~20 s | ~0.15 s to first audio |

Total with defaults: about 10 GB of the 24 GB VRAM while the assistant is running, leaving room
for the Ternary model (7.2 GB weights) or other GPU work.

## Glossary

- **Profile** – a named LLM configuration under `llm.profiles` (endpoint, model id, sampling, how to launch a server for it).
- **Backend** – a Python class implementing one of the small protocols in `alveus/llm|stt|tts/base.py`.
- **MCP** – Model Context Protocol: a standard for exposing tools to LLM agents. Each Alveus tool group is an MCP server process.
- **ToolHub** – the MCP client inside Alveus that connects all servers and presents their tools to the model as `server__tool`.
- **Activation** – how a turn starts: saying a name, an openWakeWord phrase, the hotkey, or the HTTP trigger.
- **Follow-up window** – a period after an answer in which speech is accepted without a name.
- **Barge-in** – interrupting the assistant while it is speaking.
