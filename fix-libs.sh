#!/bin/bash
set -euo pipefail

# Adjust if your clone is somewhere else
SRC="${SRC:-$HOME/src/llama.cpp-adaptive-kv-streaming}"
BUILD="$SRC/build-v2"

if [[ ! -d "$BUILD" ]]; then
  echo "Build dir not found: $BUILD"
  echo "Set SRC=/path/to/clone and re-run"
  exit 1
fi

echo "Installing shared libraries from $BUILD..."

# Copy the llama / ggml shared libs that the server needs
sudo find "$BUILD" -name 'libllama*.so*' -o -name 'libggml*.so*' \
  | sudo xargs -I{} cp -v {} /usr/local/lib/

sudo ldconfig

echo "Done. Test with:"
echo "  sudo -u llama /usr/local/bin/llama-server-kvstream --help | head -3"
