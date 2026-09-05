# Installation

## Requirements

| requirement | notes |
|---|---|
| Linux (tested: Ubuntu 24.04, GNOME on X11) | Wayland works except global hotkey / xdotool typing (use `alveus trigger` from a DE shortcut) |
| NVIDIA GPU with ≥ 12 GB VRAM, driver ≥ 550 | Bonsai 1-bit + speech models need ~10 GB; 24 GB is comfortable |
| CUDA toolkit (`nvcc`) 12.x, cmake, gcc | only to build llama.cpp; PyTorch wheels bring their own CUDA runtime |
| Miniconda/Anaconda (or plain `python3 -m venv` with `--venv`) | Python 3.12 |
| PipeWire (`pw-record`, `pw-play`, `wpctl`) | default on modern desktops; otherwise PortAudio via `libportaudio2` |
| ~15 GB disk | 3.8 GB Bonsai 1-bit, 7.2 GB Ternary (optional), ~3 GB speech models, ~8 GB Python env |
| Internet for the initial download | Hugging Face (models), PyPI, GitHub (llama.cpp fork) |

Optional but recommended for full desktop control: `sudo apt install xdotool wmctrl xclip playerctl`.

## One-command install on a new machine

```bash
git clone <your remote> alveus-ai
cd alveus-ai
./install.sh --ternary --with-chatterbox --services
```

What it does, in order (each step is also a standalone script under `scripts/`):

1. **System check** – NVIDIA driver, build tools, which optional desktop binaries are missing.
2. **Python env** – `conda create -n alveus -c conda-forge python=3.12 portaudio ffmpeg`, then
   `scripts/pip_install_env.sh`: PyTorch (CUDA wheels), the package in editable mode with the
   selected extras, openWakeWord without its obsolete `tflite-runtime` pin, the GPU-only build
   of onnxruntime, Parakeet, and (with `--with-chatterbox`) Chatterbox.
3. **llama.cpp** – `scripts/build_llama.sh` clones `PrismML-Eng/llama.cpp` (needed for Bonsai's
   `Q1_0`/`PQ2_0` kernels) into `~/local/lib/llama.cpp-bonsai` and builds `llama-server` and
   `llama-cli` with `-DGGML_CUDA=ON` for the GPU's compute capability (auto-detected).
4. **Models** – `scripts/download_models.sh`: Bonsai-27B 1-bit (and Ternary with `--ternary`) into
   `~/local/model/`, plus pre-caching Whisper, Kokoro and the `hey_jarvis` wake word.
   Only the needed GGUF files are fetched (the repos also contain 54 GB F16 files).
5. **Config** – writes `config/local.yaml` with the model dir, llama-server path, and your name.
6. **Services** (`--services`) – renders and enables `alveus-llm.service` and `alveus.service`
   as systemd user units.

Flags: `--env NAME`, `--venv`, `--models DIR`, `--lib DIR`, `--ternary`, `--no-1bit`,
`--with-chatterbox`, `--no-parakeet`, `--services`, `--skip-llama`, `--skip-models`.

## Opening the GUI

Once the `alveus` service (or `alveus talk` / `alveus api`) is running, the browser GUI is at
`http://127.0.0.1:8765/` — `alveus ui` opens it. It is bound to the local machine; for a remote
machine use `ssh -L 8765:127.0.0.1:8765 <host>` and browse to the same address.

## Verifying

```bash
conda activate alveus
alveus doctor --warm      # GPU, torch CUDA, audio backend, weights, llama-server, endpoint, every dep, model loads
alveus tools              # all MCP servers start and list their tools
alveus llm test           # streams a reply from the LLM
alveus tts say "Hello"    # speaker works
alveus stt test           # microphone works (speak for 5 s)
```

## Directory layout on this machine

| path | contents |
|---|---|
| `~/local/repo/alveus-ai` | this repository (`ALVEUS_HOME`) |
| `~/local/model/bonsai/Bonsai-27B-Q1_0.gguf` | 1-bit weights (3.8 GB) |
| `~/local/model/bonsai-ternary/Ternary-Bonsai-27B-PQ2_0.gguf` | ternary weights (7.2 GB) |
| `~/local/model/wakeword/` | custom openWakeWord `.onnx` models (empty until you train one) |
| `~/local/lib/llama.cpp-bonsai/build/bin/llama-server` | inference server binary |
| `~/miniconda3/envs/alveus` | Python environment |
| `~/.cache/huggingface/hub` | faster-whisper, Kokoro, Parakeet, Chatterbox weights |
| `~/miniconda3/envs/alveus/lib/python3.12/site-packages/openwakeword/resources/models` | pretrained wake-word models |
| `~/.config/systemd/user/alveus*.service` | rendered service units |
| `~/.config/opencode/opencode.jsonc` | opencode provider `bonsai` pointing at llama-server |
| `~/local/repo/alveus-ai/logs/alveus.log` | rotating text log (also `journalctl --user -u alveus`) |

## Services

Both units are enabled and start automatically at login, so a reboot needs no manual steps
(models take about a minute to load).

```bash
systemctl --user stop alveus alveus-llm        # stop everything
systemctl --user start alveus-llm alveus       # start everything
systemctl --user status alveus-llm alveus      # state
systemctl --user restart alveus                # after config changes
systemctl --user disable alveus alveus-llm     # stop autostart
journalctl --user -u alveus -f                 # live log
```

`alveus.service` runs `alveus talk`; it does not wait for the LLM, so the GUI is reachable even
while `alveus-llm` is still loading or failing (the header shows the LLM state). It inherits `DISPLAY`/`XAUTHORITY` from the systemd user environment, which GDM
populates at login; if the hotkey reports no display, run
`systemctl --user import-environment DISPLAY XAUTHORITY` and restart the unit.

## Updating

```bash
cd ~/local/repo/alveus-ai && git pull
conda activate alveus && scripts/pip_install_env.sh --with-chatterbox   # if deps changed
scripts/install_services.sh --start                                      # re-render units if they changed
```

`requirements-lock.txt` records the exact versions that were verified together on 2026-09-04.

## Uninstall

```bash
systemctl --user disable --now alveus alveus-llm && rm ~/.config/systemd/user/alveus*.service
conda env remove -n alveus
rm -rf ~/local/repo/alveus-ai ~/local/lib/llama.cpp-bonsai
rm -rf ~/local/model/bonsai ~/local/model/bonsai-ternary ~/local/model/wakeword   # weights
```
