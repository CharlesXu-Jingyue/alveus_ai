#!/usr/bin/env bash
# Qwen3-TTS (tts.backend: qwen3) in its own small environment.
#
# qwen-tts pins transformers 4.57 while Alveus runs on transformers 5, so the engine runs as a worker
# process (alveus/tts/qwen3_worker.py) with this environment's Python: a venv on top of the Alveus
# Python (it reuses torch, numpy, librosa ... from there) that adds only qwen-tts and its pins.
#
#   scripts/install_qwen3_tts.sh [--weights DIR] [--model 1_7b|0_6b|both]
#
#   --weights DIR   also download the model weights into DIR/<model name> (and use them from there:
#                   set tts.qwen3.weights_dir to DIR). Without it they are downloaded on first use
#                   into DIR if tts.qwen3.weights_dir is set, else into the Hugging Face cache.
# Run it with the Alveus environment active (conda activate alveus).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
WEIGHTS=""; MODEL=1_7b
while [ $# -gt 0 ]; do
  case "$1" in
    --weights) WEIGHTS="$2"; shift;; --model) MODEL="$2"; shift;;
    -h|--help) sed -n '2,14p' "$0"; exit 0;;
    *) echo "unknown option $1"; exit 1;;
  esac; shift
done
PY="${ALVEUS_PYTHON:-$(command -v python)}"
"$PY" -c "import torch, librosa, soundfile" 2>/dev/null || { echo "Activate the Alveus environment first (conda activate alveus)"; exit 1; }
VENV="$HERE/.venv-qwen3tts"
echo "== Qwen3-TTS environment in $VENV (on top of $PY)"
[ -x "$VENV/bin/python" ] || "$PY" -m venv --system-site-packages "$VENV"
"$VENV/bin/python" -m pip install -q --no-deps "qwen-tts==0.1.1"
"$VENV/bin/python" -m pip install -q "transformers==4.57.3" "accelerate==1.12.0" "huggingface_hub>=0.34,<1.0" sox
"$VENV/bin/python" -c "import qwen_tts, transformers; print('qwen-tts ready, transformers', transformers.__version__)" 2>/dev/null \
  | grep -v '^\*\|flash-attn' || true

if [ -n "$WEIGHTS" ]; then
  mkdir -p "$WEIGHTS"
  case "$MODEL" in both) NAMES=(1.7B 0.6B);; 0_6b) NAMES=(0.6B);; *) NAMES=(1.7B);; esac
  for n in "${NAMES[@]}"; do
    repo="Qwen/Qwen3-TTS-12Hz-${n}-Base"
    echo "== Downloading $repo into $WEIGHTS"
    "$VENV/bin/python" -c "from huggingface_hub import snapshot_download as d; d('$repo', local_dir='$WEIGHTS/${repo#Qwen/}')"
  done
  echo "Set tts.qwen3.weights_dir: $WEIGHTS (Settings → Voice → Qwen3-TTS → Model folder, or config/local.yaml)."
fi
echo "Choose it in Settings → Voice → Qwen3-TTS, or tts.backend: qwen3."
