#!/usr/bin/env python3
"""comfy_run.py — run FLUX.2 Klein (image) or Wan 2.2 5B (video) through ComfyUI's API, via llama-swap.

Going through llama-swap (/upstream/comfyui/...) makes llama-swap unload any LLM and start ComfyUI first.
Workflows are API-format translations of ComfyUI's bundled templates
(image_flux2_klein_text_to_image.json "Distilled" subgraph, video_wan2_2_5B_ti2v.json).

  python3 comfy_run.py image "a lighthouse in a storm, oil painting"
  python3 comfy_run.py video "a cat walking along a garden wall at sunset" --seconds 3
Outputs land in /models/comfyui/output/.
"""
import argparse, json, os, random, re, sys, time, urllib.request

URL = os.environ.get("LLAMA_SWAP_URL", "http://127.0.0.1:8081") + "/upstream/comfyui"


def key():
    if os.environ.get("LLAMA_SWAP_KEY"):
        return os.environ["LLAMA_SWAP_KEY"]
    return re.search(r'"(sk-[a-f0-9]+)"', open("/etc/llama-swap/config.yaml").read()).group(1)


HDR = {"Authorization": f"Bearer {key()}", "Content-Type": "application/json"}


def call(path, body=None, timeout=900):
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode() if body else None, headers=HDR)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def flux2_klein(prompt, w=1024, h=1024, seed=None):
    """FLUX.2 Klein 4B distilled: 4 steps, CFG 1, zeroed negative."""
    return {
        "70": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux-2-klein-4b.safetensors", "weight_dtype": "default"}},
        "71": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "flux2", "device": "default"}},
        "72": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "74": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["71", 0]}},
        "76": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["74", 0]}},
        "63": {"class_type": "CFGGuider", "inputs": {"cfg": 1, "model": ["70", 0], "positive": ["74", 0], "negative": ["76", 0]}},
        "61": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "62": {"class_type": "Flux2Scheduler", "inputs": {"steps": 4, "width": w, "height": h}},
        "66": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "73": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed if seed is not None else random.randrange(2**48)}},
        "64": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["73", 0], "guider": ["63", 0], "sampler": ["61", 0],
                                                                 "sigmas": ["62", 0], "latent_image": ["66", 0]}},
        "65": {"class_type": "VAEDecode", "inputs": {"samples": ["64", 0], "vae": ["72", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "flux2-klein", "images": ["65", 0]}},
    }


WAN_NEG = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，"
           "多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走")


def wan22_5b(prompt, seconds=2, w=1280, h=704, steps=20, seed=None):
    """Wan 2.2 TI2V-5B text-to-video at 24 fps (template: 20 steps, CFG 5, uni_pc, shift 8)."""
    frames = int(seconds * 24) // 4 * 4 + 1  # Wan wants 4n+1 frames
    return {
        "37": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors", "weight_dtype": "default"}},
        "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "48": {"class_type": "ModelSamplingSD3", "inputs": {"shift": 8, "model": ["37", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["38", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": WAN_NEG, "clip": ["38", 0]}},
        "55": {"class_type": "Wan22ImageToVideoLatent", "inputs": {"width": w, "height": h, "length": frames, "batch_size": 1, "vae": ["39", 0]}},
        "3": {"class_type": "KSampler", "inputs": {"seed": seed if seed is not None else random.randrange(2**48), "steps": steps, "cfg": 5,
                                                   "sampler_name": "uni_pc", "scheduler": "simple", "denoise": 1,
                                                   "model": ["48", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["55", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
        "57": {"class_type": "CreateVideo", "inputs": {"fps": 24, "images": ["8", 0]}},
        "58": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "video/wan22-5b", "format": "auto", "codec": "auto", "video": ["57", 0]}},
    }


def run(workflow):
    t0 = time.time()
    pid = call("/prompt", {"prompt": workflow})["prompt_id"]
    while True:
        h = call(f"/history/{pid}").get(pid)
        if h and h.get("status", {}).get("completed") is not None:
            break
        time.sleep(2)
    status = h["status"]
    if status.get("status_str") != "success":
        sys.exit("FAILED: " + json.dumps(status.get("messages"))[-1500:])
    files = [f"{o.get('subfolder', '')}/{o['filename']}".lstrip("/")
             for out in h["outputs"].values() for k in ("images", "videos", "gifs") for o in out.get(k, [])]
    print(f"done in {time.time() - t0:.1f}s -> " + ", ".join(f"/models/comfyui/output/{f}" for f in files))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["image", "video"])
    ap.add_argument("prompt")
    ap.add_argument("--seconds", type=float, default=2)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    run(flux2_klein(a.prompt, seed=a.seed) if a.kind == "image" else wan22_5b(a.prompt, a.seconds, seed=a.seed))
