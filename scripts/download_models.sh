#!/usr/bin/env bash
# Download LLM weights (and pre-fetch speech models) into $ALVEUS_MODELS.
# Usage: scripts/download_models.sh [--ternary] [--no-1bit] [--speech]
set -euo pipefail
MODELS="${ALVEUS_MODELS:-$HOME/local/model}"
ONEBIT=1; TERNARY=0; SPEECH=0
for a in "$@"; do case "$a" in --ternary) TERNARY=1;; --no-1bit) ONEBIT=0;; --speech) SPEECH=1;; esac; done
command -v hf >/dev/null || python -m pip install -U huggingface_hub
if [ "$ONEBIT" = 1 ]; then
  hf download prism-ml/Bonsai-27B-gguf Bonsai-27B-Q1_0.gguf --local-dir "$MODELS/bonsai"
fi
if [ "$TERNARY" = 1 ]; then
  hf download prism-ml/Ternary-Bonsai-27B-gguf Ternary-Bonsai-27B-PQ2_0.gguf --local-dir "$MODELS/bonsai-ternary"
fi
if [ "$SPEECH" = 1 ]; then
  python - <<'PY'
import openwakeword.utils as u; u.download_models(model_names=["hey_jarvis"])
from faster_whisper import WhisperModel; WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
from kokoro import KPipeline; KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device="cpu")
print("speech models cached")
PY
fi
echo "models in $MODELS"
