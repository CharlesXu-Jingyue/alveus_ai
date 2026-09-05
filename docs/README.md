# Alveus documentation

| document | what it covers |
|---|---|
| [overview.md](overview.md) | What Alveus is, design goals, capabilities at a glance, hardware footprint, glossary |
| [architecture.md](architecture.md) | Components, data flow, the voice state machine, threading model, code map |
| [installation.md](installation.md) | Installing on this machine and on a fresh Linux + CUDA machine; models; services; uninstall |
| [configuration.md](configuration.md) | Every configuration key in `config/alveus.yaml`, override layers, environment variables |
| [usage.md](usage.md) | Talking to Alveus, example requests, CLI reference, service management, text mode |
| [tools.md](tools.md) | All 41 built-in MCP tools, the safety model, adding third-party servers, writing your own |
| [backends.md](backends.md) | LLM / STT / TTS / audio backends, how to swap them, measured performance, adding new ones |
| [api.md](api.md) | The browser GUI and local HTTP API (streaming chat, confirmations, config, restart) |
| [wake-words.md](wake-words.md) | Activation modes, pretrained wake words, training custom "Alveus" / "Aurea" models |
| [troubleshooting.md](troubleshooting.md) | Known issues and their fixes, diagnostic commands |
| [development.md](development.md) | Repository conventions, tests, lint, extension points, roadmap ideas |

Quick start: `conda activate alveus && alveus doctor --warm && alveus chat`, then say **"Aurea, …"** with `alveus talk` or the `alveus` systemd service — and open the GUI at http://127.0.0.1:8765/ (`alveus ui`).
