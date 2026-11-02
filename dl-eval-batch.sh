#!/bin/bash
# dl-eval-batch.sh — non-Qwen candidates for benchmarking (picked 2026-11-02).
# Sizes from the Hugging Face API. ~162 GB total. Re-runnable: wget -c resumes.
set -euo pipefail

DEST="${DEST:-/models}"
HF="https://huggingface.co"

get() {  # get <repo> <file> <subdir>
  mkdir -p "$DEST/$3"
  echo ">>> $1/$2"
  wget -q --show-progress -c -O "$DEST/$3/$2" "$HF/$1/resolve/main/$2"
}

# --- IBM Granite 4.2 8B (dense, Apache 2.0) ---
# 30B dropped: its KV cache (64 layers x 8 KV heads) caps it at ~32-64K on 24 GB.
# 8B at Q8_0 + 128K q8 KV (~11.4 GB) fits fully on GPU.
get ibm-granite/granite-4.2-8b-GGUF    granite-4.2-8b-Q8_0.gguf                 granite-4.2-8b           #  9.3 GB
get mradermacher/Granite-4.2-8B-Surgical-Abliterated-GGUF \
    Granite-4.2-8B-Surgical-Abliterated.Q8_0.gguf                               granite-4.2-8b-abl       #  9.3 GB  claims 0 refusals, no metrics

# --- Meta Muse Glimmer 30B (dense, Apache 2.0) ---
# Tiny KV cache (13 full-attn layers, 2 KV heads) -> room for Q5 at 128K.
get unsloth/Muse-Glimmer-30B-GGUF      Muse-Glimmer-30B-UD-Q5_K_M.gguf          muse-glimmer-30b         # 19.2 GB
get The-freezer/Muse-Glimmer-30B-Abliterated-GGUF \
    Muse-Glimmer-30B-Abliterated-Q5_K_M.gguf                                    muse-glimmer-30b-abl     # 19.8 GB  0/450 refusals
get 0bserverx/Muse-Glimmer-30B-Heretic-Uncensored-GGUF \
    Muse-Glimmer-30B-Heretic-Q5_K_M.gguf                                        muse-glimmer-30b-heretic # 19.8 GB  KL 0.074

# --- Google Gemma 4 31B (dense, Apache 2.0) ---
# Google's own quantization-aware-trained 4-bit: designed to be run at Q4.
get google/gemma-4-31B-it-qat-q4_0-gguf gemma-4-31B_q4_0-it.gguf                gemma-4-31b              # 17.7 GB
get unsloth/gemma-4-31B-it-GGUF        gemma-4-31B-it-UD-Q4_K_XL.gguf           gemma-4-31b-unsloth      # 18.8 GB
get unsloth/gemma-4-31B-it-GGUF        mtp-gemma-4-31B-it.gguf                  gemma-4-31b-unsloth      #  0.5 GB  speculative-decoding draft
get HauhauCS/Gemma4-31B-QAT-Uncensored-HauhauCS-Balanced-MTP \
    Gemma4-31B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf                     gemma-4-31b-hauhau       # 18.7 GB  QAT-based, 0/465 refusals
get mradermacher/gemma-4-31B-it-abliterated-GGUF \
    gemma-4-31B-it-abliterated.Q4_K_M.gguf                                      gemma-4-31b-abl          # 18.7 GB  wangzhang, 7/100 refusals

echo "Done."
du -sh "$DEST"/granite-4.2-8b* "$DEST"/muse-glimmer-30b* "$DEST"/gemma-4-31b*
