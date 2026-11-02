#!/bin/bash
# dl-comfy-models.sh — image + video weights for ComfyUI (official Comfy-Org repackages). ~34 GB.
set -euo pipefail
M="${M:-/models/comfyui/models}"
HF="https://huggingface.co"

get() {  # get <repo> <path-in-repo> <comfy subdir>
  mkdir -p "$M/$3"
  echo ">>> $1/$2"
  wget -q -c -O "$M/$3/$(basename "$2")" "$HF/$1/resolve/main/$2"
}

# FLUX.2 Klein 4B — image, Apache 2.0 (~16 GB)
get Comfy-Org/Flux-2-Klein-4B split_files/diffusion_models/flux-2-klein-4b.safetensors diffusion_models
get Comfy-Org/Flux-2-Klein-4B split_files/text_encoders/qwen_3_4b.safetensors          text_encoders
get Comfy-Org/Flux-2-Klein-4B split_files/vae/flux2-vae.safetensors                    vae

# Wan 2.2 TI2V-5B — text/image-to-video, Apache 2.0 (~18 GB)
get Comfy-Org/Wan-2.2 split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors     diffusion_models
get Comfy-Org/Wan-2.2 split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors text_encoders
get Comfy-Org/Wan-2.2 split_files/vae/wan2.2_vae.safetensors                           vae

chown -R llama:llama "$M"
echo "Done."
du -sh "$M"/diffusion_models "$M"/text_encoders "$M"/vae
