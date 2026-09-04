#!/usr/bin/env bash
# Installs Alveus python deps into the *currently active* python env.
# Usage: scripts/pip_install_env.sh [--with-chatterbox] [--with-parakeet]
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
WITH_CHATTERBOX=0; WITH_PARAKEET=1
for a in "$@"; do
  case "$a" in
    --with-chatterbox) WITH_CHATTERBOX=1;;
    --with-parakeet) WITH_PARAKEET=1;;
    --no-parakeet) WITH_PARAKEET=0;;
  esac
done
echo "== python: $(python -c 'import sys;print(sys.executable, sys.version.split()[0])')"
set -x
python -m pip install -U pip wheel setuptools
# 1) torch (CUDA 12.x wheels on Linux; brings cuDNN 9 + cuBLAS 12 libs used by faster-whisper/ctranslate2 too)
python -m pip install "torch>=2.5" "torchaudio>=2.5"
# 2) core + standard backends
python -m pip install -e "$HERE[vad,stt-whisper,tts-kokoro,wakeword,dev]"
# 3) openwakeword without its dead tflite-runtime pin (we run it on onnxruntime)
python -m pip install --no-deps "openwakeword>=0.6.0"
# 3b) onnxruntime: keep only the GPU build (the CPU wheel shadows CUDAExecutionProvider)
if python -m pip show onnxruntime >/dev/null 2>&1; then
  python -m pip uninstall -y onnxruntime && python -m pip install --force-reinstall --no-deps "onnxruntime-gpu>=1.19"
fi
# 4) optional backends
if [ "$WITH_PARAKEET" = 1 ]; then python -m pip install -e "$HERE[stt-parakeet]" || echo "WARN: parakeet install failed (optional)"; fi
if [ "$WITH_CHATTERBOX" = 1 ]; then python -m pip install -e "$HERE[tts-chatterbox]" || echo "WARN: chatterbox install failed (optional)"; fi
# chatterbox pulls the CPU onnxruntime back in; drop it again
if python -m pip show onnxruntime >/dev/null 2>&1; then python -m pip uninstall -y onnxruntime; python -m pip install --force-reinstall --no-deps "onnxruntime-gpu>=1.19"; fi
set +x
python -m pip check || true
echo "== done"
