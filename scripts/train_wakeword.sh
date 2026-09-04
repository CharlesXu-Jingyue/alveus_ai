#!/usr/bin/env bash
# Train a custom wake word with livekit-wakeword and install it for Alveus.
# Usage: scripts/train_wakeword.sh <phrase> [model_name]
#   e.g. scripts/train_wakeword.sh "alveus"      -> $ALVEUS_MODELS/wakeword/alveus.onnx
#        scripts/train_wakeword.sh "hey aurea" hey_aurea
set -euo pipefail
PHRASE="${1:?phrase required}"
NAME="${2:-$(echo "$PHRASE" | tr ' ' '_' | tr '[:upper:]' '[:lower:]')}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
MODELS="${ALVEUS_MODELS:-$(cd "$HERE" && python -c 'from alveus.config import load_config;print(load_config()._env["ALVEUS_MODELS"])')}"
OUT="$MODELS/wakeword"; WORK="$HERE/.wakeword-train/$NAME"
mkdir -p "$OUT" "$WORK/configs"
# livekit-wakeword pins newer numpy/onnxruntime than the speech stack; keep it in its own env.
TRAIN_ENV="${ALVEUS_WAKEWORD_ENV:-alveus-wakeword}"
if command -v conda >/dev/null; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda env list | grep -qE "^$TRAIN_ENV\s" || conda create -y -n "$TRAIN_ENV" python=3.12
  conda activate "$TRAIN_ENV"
fi
command -v livekit-wakeword >/dev/null || python -m pip install "livekit-wakeword[train,eval,export]"
[ -d "$HOME/.cache/livekit-wakeword" ] || livekit-wakeword setup
cat > "$WORK/configs/$NAME.yaml" <<YAML
# livekit-wakeword training config (see https://github.com/livekit/livekit-wakeword)
model_name: $NAME
target_phrases:
  - "$PHRASE"
n_samples: 10000
model:
  model_type: conv_attention
  model_size: small
steps: 50000
target_fp_per_hour: 0.2
output_dir: $WORK/out
YAML
echo "training '$PHRASE' -> $NAME (this can take a while)"
livekit-wakeword run "$WORK/configs/$NAME.yaml"
ONNX="$(find "$WORK/out" -name "*.onnx" | head -1)"
[ -n "$ONNX" ] || { echo "no .onnx produced; check $WORK/out"; exit 1; }
cp "$ONNX" "$OUT/$NAME.onnx"
echo "installed $OUT/$NAME.onnx  -> set activation.wake_word.oww_model: $NAME (mode: oww or both)"
