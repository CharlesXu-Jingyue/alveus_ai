#!/usr/bin/env bash
# Download LLM weights into $ALVEUS_MODELS/llm/ (and pre-fetch speech models).
# Usage: scripts/download_models.sh [--ternary] [--no-1bit] [--extra] [--speech]
#   --extra   the further local models with profiles in config/alveus.yaml (about 94 GB):
#             Ternary Bonsai 2 27B, LFM2.5 24B-A2B MoE, LFM3 1.7B, stock Qwen3.8 27B and three variants
# Layout: $ALVEUS_MODELS/llm/<model>/ (GGUF), $ALVEUS_MODELS/tts/ (Qwen3-TTS), $ALVEUS_MODELS/wakeword/
set -euo pipefail
MODELS="${ALVEUS_MODELS:-$HOME/local/model}"
LLM="$MODELS/llm"
ONEBIT=1; TERNARY=0; EXTRA=0; SPEECH=0
for a in "$@"; do case "$a" in --ternary) TERNARY=1;; --no-1bit) ONEBIT=0;; --extra) EXTRA=1;; --speech) SPEECH=1;; esac; done
command -v hf >/dev/null || python -m pip install -U huggingface_hub
if [ "$ONEBIT" = 1 ]; then
  hf download prism-ml/Bonsai-27B-gguf Bonsai-27B-Q1_0.gguf --local-dir "$LLM/bonsai"
fi
if [ "$TERNARY" = 1 ]; then
  hf download prism-ml/Ternary-Bonsai-27B-gguf Ternary-Bonsai-27B-PQ2_0.gguf --local-dir "$LLM/bonsai-ternary"
fi
if [ "$EXTRA" = 1 ]; then
  hf download OS-Software/Ternary-Bonsai-2-27B-Uncensored-Heretic-v2-GGUF \
    Ternary-Bonsai-2-27B-Uncensored-Heretic-v2-PQ2_0.gguf --local-dir "$LLM/bonsai2-ternary"
  hf download abenzerps/LFM2.5-24B-A2B-Uncensored-GSQ-RCO-GGUF \
    LFM2.5-24B-A2B-GSQ-RCO-IQ4_XS.gguf LFM2.5-24B-A2B-DSpark-Q8_0.gguf --local-dir "$LLM/lfm2.5-24b-a2b"
  hf download AtomicChat/LFM3-1.7B-Uncensored-GGUF LFM3-1.7B-Uncensored-AD-Q6_K.gguf --local-dir "$LLM/lfm3-1.7b"
  hf download HauhauCS/Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP-GGUF \
    Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-Q4_K_P.gguf --local-dir "$LLM/qwen3.8-27b-direct"
  hf download DavidAU/Qwen3.8-27B-TURBO-Fable-Cold-Fusion-735-882-Heretic-Uncensored-NEO-CODER-MAX-MTP-GGUF \
    Qwen3.8-27B-TurboFCFusion-735-882-Here-Uncen-NEO-CODER-MAX-MTP-Q4_K_M.gguf --local-dir "$LLM/qwen3.8-27b-coder"
  hf download orcarouter/Qwen3.8-27B-Uncensored-GGUF Qwen3.8-27B-Uncensored-Q4_K_M.gguf --local-dir "$LLM/qwen3.8-27b-abliterated"   # gated: accept its terms on the page first
  hf download unsloth/Qwen3.8-27B-GGUF Qwen3.8-27B-UD-Q4_K_M.gguf MTP/mtp-Qwen3.8-27B-Q4_0.gguf --local-dir "$LLM/qwen3.8-27b"
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
