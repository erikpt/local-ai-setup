#!/bin/bash
# install-comfyui.sh — ComfyUI (image + video) in /models/comfyui, owned by the llama user.
# Needs: apt install python3.14-venv python3.14-dev ffmpeg
set -euo pipefail
DIR="${DIR:-/models/comfyui}"
TAG="${TAG:-v0.43.0}"   # Comfy-Org/ComfyUI release, 2026-10-27

[[ -d $DIR/.git ]] || git clone -q --branch "$TAG" --depth 1 https://github.com/Comfy-Org/ComfyUI.git "$DIR"
[[ -x $DIR/venv/bin/python ]] || python3.14 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
# CUDA 13 build of PyTorch (driver 615 supports CUDA 13)
"$DIR/venv/bin/pip" install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130
"$DIR/venv/bin/pip" install -q -r "$DIR/requirements.txt"
chown -R llama:llama "$DIR"
# Import check only — does not initialise CUDA, so it's safe while the GPU is busy.
"$DIR/venv/bin/python" -c "import torch; print('torch', torch.__version__, 'built for CUDA', torch.version.cuda)"
echo "ComfyUI $TAG installed in $DIR"
