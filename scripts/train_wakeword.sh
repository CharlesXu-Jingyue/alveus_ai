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
# ~19 GB of shared training data (ACAV100M features, MUSAN, RIRs, Piper voice): keep it out of the repo.
DATA="${ALVEUS_WAKEWORD_DATA:-$MODELS/wakeword-train-data}"
mkdir -p "$OUT" "$WORK/configs" "$DATA"
# livekit-wakeword pins newer numpy/onnxruntime than the speech stack; keep it in its own env.
TRAIN_ENV="${ALVEUS_WAKEWORD_ENV:-alveus-wakeword}"
if command -v conda >/dev/null; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda env list | grep -qE "^$TRAIN_ENV\s" || conda create -y -n "$TRAIN_ENV" python=3.12
  conda activate "$TRAIN_ENV"
fi
command -v livekit-wakeword >/dev/null || python -m pip install "livekit-wakeword[train,eval,export]"
# Piper's phonemizer shells out to the espeak-ng binary (apt: espeak-ng). If only the library is
# installed (libespeak-ng1 + espeak-ng-data, pulled in by other packages), build the small CLI into the env.
if ! command -v espeak-ng >/dev/null; then
  if [ -e /usr/lib/x86_64-linux-gnu/libespeak-ng.so.1 ] && command -v gcc >/dev/null; then
    echo "building espeak-ng CLI against the system libespeak-ng"
    T="$(mktemp -d)"; curl -sL https://github.com/espeak-ng/espeak-ng/archive/refs/tags/1.51.tar.gz | tar xz -C "$T"
    printf '#define PACKAGE_VERSION "1.51"\n#define PATH_ESPEAK_DATA "/usr/lib/x86_64-linux-gnu/espeak-ng-data"\n' > "$T/espeak-ng-1.51/src/include/config.h"
    gcc -O2 -I "$T/espeak-ng-1.51/src/include" -o "$(dirname "$(command -v python)")/espeak-ng" \
        "$T/espeak-ng-1.51/src/espeak-ng.c" /usr/lib/x86_64-linux-gnu/libespeak-ng.so.1 && rm -rf "$T"
  else
    echo "espeak-ng is required: sudo apt install espeak-ng"; exit 1
  fi
fi
[ -d "$DATA/features" ] || livekit-wakeword setup --data-dir "$DATA"
cat > "$WORK/configs/$NAME.yaml" <<YAML
# livekit-wakeword training config (see https://github.com/livekit/livekit-wakeword)
model_name: $NAME
data_dir: $DATA
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
