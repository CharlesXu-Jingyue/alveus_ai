#!/usr/bin/env bash
# ------------------------------------------------------------------------------------------
# Alveus installer for Linux + NVIDIA CUDA machines.
#
#   git clone <repo> alveus-ai && cd alveus-ai && ./install.sh
#
# Options:
#   --env NAME          conda env name (default: alveus)        --venv  use python -m venv instead of conda
#   --models DIR        where model weights live (default: ~/local/model)
#   --lib DIR           where llama.cpp is built (default: ~/local/lib)
#   --ternary           also download Ternary-Bonsai-27B          --no-1bit  skip Bonsai 1-bit
#   --with-chatterbox   install Chatterbox TTS (heavier)        --no-parakeet  skip Parakeet STT
#   --services          install & enable systemd --user units
#   --skip-llama        don't build llama.cpp (set ALVEUS_LLAMA_SERVER yourself)
#   --skip-models       don't download anything
# ------------------------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_NAME=alveus; USE_VENV=0; MODELS="$HOME/local/model"; LIB="$HOME/local/lib"
TERNARY=0; ONEBIT=1; CHATTERBOX=0; PARAKEET=1; SERVICES=0; SKIP_LLAMA=0; SKIP_MODELS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift;; --venv) USE_VENV=1;; --models) MODELS="$2"; shift;; --lib) LIB="$2"; shift;;
    --ternary) TERNARY=1;; --no-1bit) ONEBIT=0;; --with-chatterbox) CHATTERBOX=1;; --no-parakeet) PARAKEET=0;;
    --services) SERVICES=1;; --skip-llama) SKIP_LLAMA=1;; --skip-models) SKIP_MODELS=1;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) echo "unknown option $1"; exit 1;;
  esac; shift
done
say() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

say "Checking system"
command -v nvidia-smi >/dev/null || { echo "nvidia-smi not found: install the NVIDIA driver first"; exit 1; }
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
for b in git cmake gcc g++ nvcc; do command -v $b >/dev/null || echo "WARNING: '$b' missing (needed to build llama.cpp): sudo apt install build-essential cmake nvidia-cuda-toolkit"; done
MISSING_APT=()
for b in xdotool wmctrl xclip notify-send playerctl; do command -v $b >/dev/null || MISSING_APT+=("$b"); done
command -v pw-record >/dev/null || MISSING_APT+=("pipewire-bin")

say "Python environment ($([ $USE_VENV = 1 ] && echo venv || echo "conda env '$ENV_NAME'"))"
if [ "$USE_VENV" = 1 ]; then
  [ -d "$HERE/.venv" ] || python3 -m venv "$HERE/.venv"
  # shellcheck disable=SC1091
  source "$HERE/.venv/bin/activate"
  command -v pw-record >/dev/null || echo "NOTE: without PipeWire, sounddevice needs libportaudio2 (sudo apt install libportaudio2)"
else
  CONDA_BASE="$(conda info --base 2>/dev/null || true)"
  [ -n "$CONDA_BASE" ] || { echo "conda not found: install Miniconda or re-run with --venv"; exit 1; }
  # shellcheck disable=SC1091
  source "$CONDA_BASE/etc/profile.d/conda.sh"
  conda env list | grep -qE "^$ENV_NAME\s" || conda create -y -n "$ENV_NAME" -c conda-forge python=3.12 portaudio ffmpeg
  conda activate "$ENV_NAME"
fi
ARGS=(); [ $CHATTERBOX = 1 ] && ARGS+=(--with-chatterbox); [ $PARAKEET = 0 ] && ARGS+=(--no-parakeet)
"$HERE/scripts/pip_install_env.sh" "${ARGS[@]}"
PY="$(command -v python)"

if [ "$SKIP_LLAMA" = 0 ]; then
  say "Building PrismML llama.cpp (CUDA)"
  ALVEUS_LIB="$LIB" "$HERE/scripts/build_llama.sh"
  LLAMA_SERVER="$LIB/llama.cpp-bonsai/build/bin/llama-server"
else
  LLAMA_SERVER="${ALVEUS_LLAMA_SERVER:-llama-server}"
fi

if [ "$SKIP_MODELS" = 0 ]; then
  say "Downloading models into $MODELS"
  DL=(); [ $TERNARY = 1 ] && DL+=(--ternary); [ $ONEBIT = 0 ] && DL+=(--no-1bit)
  ALVEUS_MODELS="$MODELS" "$HERE/scripts/download_models.sh" "${DL[@]}" --speech
fi

say "Writing config/local.yaml"
mkdir -p "$HERE/logs" "$MODELS/wakeword"
if [ ! -f "$HERE/config/local.yaml" ]; then
cat > "$HERE/config/local.yaml" <<YAML
# Machine-specific overrides (git-ignored). Edit freely; defaults are in alveus.yaml.
env:
  ALVEUS_MODELS: $MODELS
  ALVEUS_LLAMA_SERVER: $LLAMA_SERVER
assistant:
  user_name: $(getent passwd "$USER" | cut -d: -f5 | cut -d, -f1 | awk '{print $1}')
YAML
[ $TERNARY = 1 ] && [ $ONEBIT = 0 ] && printf 'llm:\n  profile: bonsai-ternary\n' >> "$HERE/config/local.yaml"
else
  echo "config/local.yaml exists - leaving it alone"
fi

if [ "$SERVICES" = 1 ]; then
  say "Installing systemd --user services"
  PYTHON_BIN="$PY" ALVEUS_MODELS="$MODELS" "$HERE/scripts/install_services.sh" --enable
fi

say "Done"
[ ${#MISSING_APT[@]} -gt 0 ] && echo "Optional desktop tools missing; for full desktop control run:  sudo apt install ${MISSING_APT[*]}"
cat <<TXT

Next steps:
  $([ $USE_VENV = 1 ] && echo "source $HERE/.venv/bin/activate" || echo "conda activate $ENV_NAME")
  alveus doctor --warm          # verify everything
  alveus llm serve &            # start the LLM (or: systemctl --user start alveus-llm)
  alveus chat                   # text mode with tools
  alveus talk                   # voice mode (say "hey jarvis" or press ctrl+alt+space)
TXT
