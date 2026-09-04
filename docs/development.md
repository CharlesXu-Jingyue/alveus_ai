# Development

## Setup

```bash
conda activate alveus
pip install -e ".[dev]"
python -m pytest -q tests          # unit tests (config, sentence splitter, name matcher)
python -m ruff check alveus mcp_servers
```

Integration checks that need the running stack: `alveus doctor --warm`, `alveus tools`,
`alveus llm test`, `printf 'what is my gpu temperature?\n/quit\n' | alveus chat`.

## Conventions

- Python ≥ 3.11, type hints, `from __future__ import annotations`.
- One backend per file; register in the package `__init__` factory (`make_llm`, `make_stt`,
  `make_tts`). Backends load lazily (`load()`), so unused engines cost nothing.
- Heavy imports (torch, faster_whisper, kokoro, chatterbox, onnx_asr, openwakeword) happen
  inside `load()`/`__init__` of the backend, never at module import.
- Everything user-facing reads configuration via `load_config()`; no hard-coded paths.
- MCP servers return JSON strings via `j()`; mark irreversible tools with `annot(destructive=True)`.
- Logging through `logging.getLogger(__name__)`; the CLI installs a Rich handler and a file handler.

## Repository map

```
alveus/            core package (see architecture.md)
mcp_servers/       built-in MCP servers
config/            alveus.yaml (defaults), persona.md, local.yaml (git-ignored)
scripts/           installer pieces: pip_install_env.sh, build_llama.sh, download_models.sh,
                   install_services.sh, train_wakeword.sh
systemd/           *.service.in templates rendered by install_services.sh
tests/             pytest unit tests
docs/              this documentation
install.sh         end-to-end installer for a new machine
requirements-lock.txt   versions verified together on 2026-09-04
```

## Extension points and ideas

- **Streaming STT** for lower latency (Whisper streaming, Parakeet streaming via sherpa-onnx).
- **Voice barge-in in names mode** – run a tiny STT on speech during playback, or train the
  custom wake-word models (`scripts/train_wakeword.sh`) and use `mode: both`.
- **Memory** – a notes/vector store MCP server so the assistant remembers facts across sessions
  (history is currently per process).
- **Timers/reminders** – an MCP server with a scheduler and `/speak` callbacks.
- **Home Assistant** – enable the example server block in `config/alveus.yaml`.
- **Vision** – Bonsai ships an `mmproj` vision tower; llama-server can take images
  (`--mmproj`), so a `screenshot → describe` tool is feasible.
- **Multiple wake models** – `WakeWord` takes a single model today; extend to a list.
- **Speaker identification** – gate destructive actions on your voice.

## Release checklist

1. `python -m pytest -q tests && python -m ruff check alveus mcp_servers`
2. `alveus doctor --warm` on a clean env created by `./install.sh --skip-models --skip-llama`
3. Update `requirements-lock.txt` (`pip freeze | grep …`) and the version in `pyproject.toml`/`alveus/__init__.py`
4. Tag and push.
