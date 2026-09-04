#!/usr/bin/env bash
# Build the PrismML llama.cpp fork (needed for Bonsai Q1_0 / PQ2_0 kernels) with CUDA.
# Usage: scripts/build_llama.sh [DEST_DIR]   (default: $ALVEUS_LIB/llama.cpp-bonsai)
set -euo pipefail
DEST="${1:-${ALVEUS_LIB:-$HOME/local/lib}/llama.cpp-bonsai}"
REPO="${LLAMA_REPO:-https://github.com/PrismML-Eng/llama.cpp}"
if [ ! -d "$DEST/.git" ]; then git clone --depth 1 "$REPO" "$DEST"; else (cd "$DEST" && git pull --ff-only || true); fi
cd "$DEST"
ARCH="${CUDA_ARCH:-}"
if [ -z "$ARCH" ] && command -v nvidia-smi >/dev/null; then
  ARCH="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d '.')"
fi
ARCH_FLAG=""; [ -n "$ARCH" ] && ARCH_FLAG="-DCMAKE_CUDA_ARCHITECTURES=$ARCH"
cmake -B build -DGGML_CUDA=ON $ARCH_FLAG -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)" --target llama-server llama-cli
echo "built: $DEST/build/bin/llama-server"
