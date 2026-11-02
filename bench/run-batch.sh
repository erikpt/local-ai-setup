#!/bin/bash
# run-batch.sh — benchmark the 2026-11-02 eval batch, with qwen3.8-27b first as the reference.
# Coding answers get up to 32K tokens (thinking models routinely use 10K+); see bench.py.
cd "$(dirname "$0")"
python3 bench.py \
  qwen3.8-27b \
  granite-4.2-8b granite-4.2-8b-abl \
  muse-glimmer-30b muse-glimmer-30b-abl muse-glimmer-30b-heretic \
  gemma-4-31b gemma-4-31b-unsloth gemma-4-31b-hauhau gemma-4-31b-abl
echo "BATCH DONE"
