#!/usr/bin/env bash
set -euo pipefail

# --- config ---
REPO_URL="https://github.com/RaymondHuang210129/llama.cpp-adaptive-kv-streaming.git"
BRANCH="feature/adaptive-kv-stream-v2"
SRC_DIR="${SRC_DIR:-$HOME/src/llama.cpp-adaptive-kv-streaming}"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"
BINARY_NAME="llama-server-kvstream"

# --- clone / update ---
if [[ ! -d "$SRC_DIR/.git" ]]; then
  echo "Cloning $BRANCH..."
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$SRC_DIR"
else
  echo "Updating existing clone..."
  cd "$SRC_DIR"
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git reset --hard "origin/$BRANCH"
fi

cd "$SRC_DIR"

# --- build ---
echo "Configuring..."
cmake -S . -B build-v2 \
  -DGGML_CUDA=ON \
  -DGGML_CUDA_FA_ALL_QUANTS=ON \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLAMA_BUILD_TESTS=OFF

echo "Building llama-server..."
cmake --build build-v2 --target llama-server -j"$(nproc)"

# --- install ---
echo "Installing to $INSTALL_DIR/$BINARY_NAME"
sudo install -m 755 build-v2/bin/llama-server "$INSTALL_DIR/$BINARY_NAME"

echo
echo "Done."
echo "Binary: $INSTALL_DIR/$BINARY_NAME"
echo
echo "Example llama-swap cmd:"
echo "  $INSTALL_DIR/$BINARY_NAME --port \${PORT} -m /path/to/model.gguf -c 131072 -ngl 99 -fa on --cache-type-k q8_0 --cache-type-v q4_0 --kv-stream-arena-mib 2048 --parallel 1"
