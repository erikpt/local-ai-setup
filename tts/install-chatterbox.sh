#!/bin/bash
# install-chatterbox.sh — Chatterbox TTS (MIT) in its own venv (its pinned deps clash with ComfyUI's).
# Weights (~3 GB, ResembleAI/chatterbox) download on first start into $DIR/hf-cache.
set -euo pipefail
DIR="${DIR:-/models/chatterbox}"
mkdir -p "$DIR/voices"
[[ -x $DIR/venv/bin/python ]] || python3.14 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
"$DIR/venv/bin/pip" install -q torch torchaudio --index-url https://download.pytorch.org/whl/cu130
"$DIR/venv/bin/pip" install -q chatterbox-tts==0.1.7 fastapi uvicorn
install -m 644 "$(dirname "$0")/server.py" "$DIR/server.py"
chown -R llama:llama "$DIR"
"$DIR/venv/bin/python" -c "import chatterbox, torch; print('chatterbox ok, torch', torch.__version__)"
echo "Chatterbox installed in $DIR. Put reference clips (5-10 s WAV) in $DIR/voices/<name>.wav"
