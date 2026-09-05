#!/usr/bin/env bash
# Build the PrismML llama.cpp fork (needed for Bonsai Q1_0 / PQ2_0 kernels) with CUDA.
# Usage: scripts/build_llama.sh [DEST_DIR]   (default: $ALVEUS_LIB/llama.cpp-bonsai)
set -euo pipefail
DEST="${1:-${ALVEUS_LIB:-$HOME/local/lib}/llama.cpp-bonsai}"
REPO="${LLAMA_REPO:-https://github.com/PrismML-Eng/llama.cpp}"
# The Bonsai kernels (Q1_0, PQ2_0, PTQ1_0 ...) live on the fork's *prism* branch, not master.
BRANCH="${LLAMA_BRANCH:-prism}"
if [ ! -d "$DEST/.git" ]; then git clone --branch "$BRANCH" --depth 1 "$REPO" "$DEST"; else (cd "$DEST" && git fetch -q origin "$BRANCH" && git checkout -q -B "$BRANCH" "origin/$BRANCH" || true); fi
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
