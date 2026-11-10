#!/usr/bin/env bash
# Build llama.cpp's llama-server with CUDA.
#   scripts/build_llama.sh [DEST_DIR]             the PrismML fork (Bonsai Q1_0 / PQ2_0 / PTQ1_0 kernels)
#                                                 default $ALVEUS_LIB/llama.cpp-bonsai -> ALVEUS_LLAMA_SERVER
#   scripts/build_llama.sh --upstream [DEST_DIR]  upstream ggml-org llama.cpp (newest architectures: LFM2.5,
#                                                 LFM3, Qwen3.8 with MTP drafting ...)
#                                                 default $ALVEUS_LIB/llama.cpp -> ALVEUS_LLAMA_SERVER_UPSTREAM
# Running it again updates the checkout and rebuilds.
set -euo pipefail
if [ "${1:-}" = "--upstream" ]; then
  shift
  DEST="${1:-${ALVEUS_LIB:-$HOME/local/lib}/llama.cpp}"
  REPO="${LLAMA_REPO:-https://github.com/ggml-org/llama.cpp}"
  BRANCH="${LLAMA_BRANCH:-master}"
else
  DEST="${1:-${ALVEUS_LIB:-$HOME/local/lib}/llama.cpp-bonsai}"
  REPO="${LLAMA_REPO:-https://github.com/PrismML-Eng/llama.cpp}"
  # The Bonsai kernels live on the fork's *prism* branch, not master.
  BRANCH="${LLAMA_BRANCH:-prism}"
fi
if [ ! -d "$DEST/.git" ]; then git clone --branch "$BRANCH" --depth 1 "$REPO" "$DEST"; else (cd "$DEST" && git fetch -q --depth 1 origin "$BRANCH" && git checkout -q -B "$BRANCH" "origin/$BRANCH" || true); fi
cd "$DEST"
echo "building $(git rev-parse --abbrev-ref HEAD) @ $(git rev-parse --short HEAD)"
ARCH="${CUDA_ARCH:-}"
if [ -z "$ARCH" ] && command -v nvidia-smi >/dev/null; then
  ARCH="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d '.')"
fi
ARCH_FLAG=""; [ -n "$ARCH" ] && ARCH_FLAG="-DCMAKE_CUDA_ARCHITECTURES=$ARCH"
cmake -B build -DGGML_CUDA=ON $ARCH_FLAG -DCMAKE_BUILD_TYPE=Release -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON
cmake --build build -j"$(nproc)" --target llama-server llama-cli
echo "built: $DEST/build/bin/llama-server"
