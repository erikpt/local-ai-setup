#!/bin/bash
set -euo pipefail

DEST="${DEST:-/models}"
BASE="https://huggingface.co/unsloth/Qwen3-Coder-Next-GGUF/resolve/main"
mkdir -p "$DEST"

# 3-bit: llama-swap "qwen3-coder-next" (default; ~1,550 tok/s prefill, ~35 tok/s gen)
echo "Downloading Unsloth Qwen3-Coder-Next UD-Q3_K_XL (~34 GB)..."
wget -c -O "$DEST/Qwen3-Coder-Next-UD-Q3_K_XL.gguf" \
  "$BASE/Qwen3-Coder-Next-UD-Q3_K_XL.gguf"

# 4-bit: llama-swap "qwen3-coder-next-q4" (higher quality, ~1,000 tok/s prefill on 24 GB)
echo "Downloading Unsloth Qwen3-Coder-Next UD-Q4_K_XL (~46 GB)..."
wget -c -O "$DEST/Qwen3-Coder-Next-UD-Q4_K_XL.gguf" \
  "$BASE/Qwen3-Coder-Next-UD-Q4_K_XL.gguf"

echo "Done."
ls -lh "$DEST"/*Coder-Next*
