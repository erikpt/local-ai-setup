# local-ai-setup

Scripts and notes for a single-GPU home AI server: local LLMs, image, video and voice generation on one
**RTX 4090 (24 GB)**, all served through [llama-swap](https://github.com/mostlygeek/llama-swap) so only one model
holds the GPU at a time and clients just ask for a model by name.

```
clients (OpenCode, Hermes, curl, browser)
        │  OpenAI-compatible API + API key
        ▼
   llama-swap :8080 ──starts/stops on demand──►  llama-server (llama.cpp)   LLMs, 128K context
                                           ├──►  ComfyUI :8188              FLUX.2 Klein images, Wan 2.2 video
                                           └──►  Chatterbox                 text-to-speech, voice cloning
```

**Hardware:** RTX 4090 24 GB · i7-8700K · 64 GB DDR4 · ASUS Z370-E (PCIe 3.0) · Ubuntu.

## Results

- **[bench/](bench/)** — benchmark of 10 open-weight LLMs (Qwen, IBM Granite, Meta Muse Glimmer, Google Gemma and
  uncensored variants) at 128K context: speed, unit-tested coding, refusals. Short version: **Muse Glimmer 30B** had
  a perfect coding score, the best long-context speed and the smallest memory footprint.
  Methodology and caveats in [bench/METHODOLOGY.md](bench/METHODOLOGY.md).
- **[samples/](samples/)** — unedited outputs from the image, video and voice models, with prompts and timings.

## What's in here

### LLM serving (llama.cpp + llama-swap)

| File | Purpose |
|---|---|
| [`build-kvstream.sh`](build-kvstream.sh) | Builds the [adaptive KV-streaming llama.cpp fork](src/) (submodule) as `llama-server-kvstream` |
| [`fix-libs.sh`](fix-libs.sh) | Installs that build's shared libraries into `/usr/local/lib` |
| [`dl-coder-next.sh`](dl-coder-next.sh) | Downloads Qwen3-Coder-Next GGUFs (Q3/Q4, MoE with CPU expert offload) |
| [`dl-eval-batch.sh`](dl-eval-batch.sh) | Downloads the Granite / Glimmer / Gemma GGUFs evaluated in `bench/` |
| [`new-llama-api-key.sh`](new-llama-api-key.sh) | Adds an API key to `/etc/llama-swap/config.yaml` and reloads llama-swap |
| [`model-stats.sh`](model-stats.sh) | Prints an earlier benchmark table plus what llama-swap currently has loaded |
| [`toksec.sh`](toksec.sh) | Quick tokens/second check against a llama-server endpoint |
| [`llama-dash.sh`](llama-dash.sh) | Terminal dashboard: GPU/CPU load, temps, throttling, live tok/s per port |

Per-model `llama-server` settings used for the benchmark (128K context, flash attention, quantized KV cache):
[`bench/models.yaml`](bench/models.yaml).

### Image and video (ComfyUI)

| File | Purpose |
|---|---|
| [`install-comfyui.sh`](install-comfyui.sh) | ComfyUI v0.43.0 into `/models/comfyui` (own venv, CUDA 13 PyTorch) |
| [`dl-comfy-models.sh`](dl-comfy-models.sh) | FLUX.2 Klein 4B (image) + Wan 2.2 TI2V-5B (video), official Comfy-Org files, Apache 2.0 |
| [`comfy/comfy_run.py`](comfy/comfy_run.py) | `comfy_run.py image "prompt"` / `comfy_run.py video "prompt" --seconds 3` via ComfyUI's API |

### Voice (Chatterbox)

| File | Purpose |
|---|---|
| [`tts/install-chatterbox.sh`](tts/install-chatterbox.sh) | Chatterbox TTS (MIT) into `/models/chatterbox` |
| [`tts/server.py`](tts/server.py) | Small OpenAI-compatible `/v1/audio/speech` server; voice cloning from `voices/<name>.wav` |

[`llama-swap-media.yaml`](llama-swap-media.yaml) has the llama-swap entries that put ComfyUI and Chatterbox
behind the same proxy as the LLMs.

## Quick start

```bash
# Chat with any configured LLM
curl localhost:8080/v1/chat/completions -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"muse-glimmer-30b","messages":[{"role":"user","content":"Hello"}]}'

# Speech
curl localhost:8080/v1/audio/speech -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"chatterbox","input":"Hello from the home server."}' -o hello.wav

# Image / video (writes to /models/comfyui/output/)
python3 comfy/comfy_run.py image "a lighthouse in a storm, oil painting"
python3 comfy/comfy_run.py video "a cat walking along a garden wall at sunset" --seconds 3

# Re-run the LLM benchmark (see bench/METHODOLOGY.md)
python3 bench/bench.py muse-glimmer-30b gemma-4-31b
```

ComfyUI's web UI is on `http://<server>:8188` once llama-swap has started it (any request to model `comfyui`).
It has no authentication — anyone who can reach that port can use it.

## Notes

- Paths assume models under `/models` and llama-swap config at `/etc/llama-swap/config.yaml`; adjust to taste.
- Only one model fits in 24 GB at a time; switching takes ~5–60 s depending on size.
- API keys live only in the llama-swap config on the server — nothing in this repo contains them.
