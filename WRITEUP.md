# One RTX 4090, everything local: a home AI server write-up

*November 2026. The machine is called **olympus**. Chat and coding LLMs at 128K context, image, video and voice
generation, and per-key access control, all on one 24 GB GPU in an eight-year-old desktop.*

**Short version:**
- **Meta Muse Glimmer 30B** is the best all-round LLM on this card. It had a perfect coding score and the best
  long-context speed, and it fits 128K context in 18.5 GB. The uncensored **Heretic** version scored the same.
- **FLUX.2 Klein 4B** makes a 1024×1024 image in 2 seconds once loaded. **Wan 2.2 5B** makes a 2-second 720p clip
  in about a minute. **Chatterbox** speaks faster than real time in under 4 GB.
- **llama-swap** keeps one model on the GPU at a time and swaps on demand.
- **keygate**, a ~490-line stdlib-Python proxy, gives each API key its own list of allowed models and logs usage to
  SQLite.

---

## Which model for which job

| Job | Use | llama-swap name | Notes |
|---|---|---|---|
| **General purpose** chat, writing, questions | Muse Glimmer 30B Heretic | `muse-glimmer-30b-heretic` | Best all-rounder in the benchmark; 128K context in 19 GB |
| **Hermes** (agent) | Muse Glimmer 30B Heretic | `muse-glimmer-30b-heretic` | Same model as OpenCode on purpose, see below |
| **OpenCode** (coding agent) | Muse Glimmer 30B Heretic | `muse-glimmer-30b-heretic` | 15/15 coding, fastest at long context, which is what agents spend their time in |
| Quick, short-context jobs | Granite 4.2 8B | `granite-4.2-8b` | 2× faster at short prompts; can get stuck reasoning on hard problems |
| Second opinion | Gemma 4 31B (Google QAT) | `gemma-4-31b` | Also 15/15, different lineage, refused nothing; slower at long context |
| **Image generation** | FLUX.2 Klein 4B (distilled) | `comfyui` | 2 s per 1024×1024 image once loaded |
| **Video generation** | Wan 2.2 TI2V-5B | `comfyui` | ~1 minute per 2-second 720p clip |
| **Voice generation** (text-to-speech) | Chatterbox | `chatterbox` | Faster than real time, ~3.8 GB, clones a voice from a 5–10 s clip |
| **Voice recognition** (speech-to-text) | *not set up yet:* Whisper large-v3-turbo on whisper.cpp | — | See below |

**Why Hermes and OpenCode should share one model.** Only one LLM fits on the GPU at a time. If Hermes used Gemma
and OpenCode used Glimmer, every switch between them would unload one model and load the other. That costs tens of
seconds and throws away the prompt cache. Pointing both at the same llama-swap name keeps the model loaded. The same
logic applies across the Heretic and stock Glimmer: they are separate files, so mixing them also forces swaps. Pick
one.

**Heretic or stock Glimmer?** They scored the same on coding and speed. Heretic is uncensored by design, though on
this benchmark's crude 10-prompt check both refused 2 of 10. Either is fine; the important thing is that every
client uses the same one.

**Agents and tool calling.** Hermes and OpenCode work by calling tools. The benchmark tested code quality, speed and
refusals, but not tool calling, so the agent recommendation rests on Glimmer's coding and long-context results.
If an agent misbehaves (malformed tool calls, loops), try `gemma-4-31b` next.

**Media models swap out the LLM.** ComfyUI and Chatterbox go through the same one-at-a-time rule. Generating an
image unloads the LLM, and the next chat request reloads it. Fine for occasional use. Keeping voice or images
loaded next to an LLM is the main argument for a second GPU (see the upgrade path).

**Voice recognition is the missing piece.** The recommended choice is
[whisper.cpp](https://github.com/ggml-org/whisper.cpp) running OpenAI's **Whisper large-v3-turbo**. It is small,
fast on a 4090 and multilingual, and its server can answer the OpenAI-style `/v1/audio/transcriptions` API.
llama-swap can host it like any other model, and keygate already reads the model name from that endpoint's upload
form.

## 1. Hardware

| Component | Spec |
|---|---|
| GPU | NVIDIA GeForce RTX 4090 24 GB GDDR6X (Gigabyte), stock clocks, 450 W limit |
| GPU link | PCIe 3.0 x16 from the CPU |
| CPU | Intel Core i7-8700K, 6 cores / 12 threads, up to 4.7 GHz |
| Motherboard | ASUS ROG Strix Z370-E Gaming, BIOS 3005 |
| RAM | 64 GB DDR4: 4 × 16 GB G.Skill F4-3200C16, running at **2133 MT/s** (XMP off) |
| Storage | Crucial P3 4 TB NVMe, holds all models |
| OS | Ubuntu 26.04.1 LTS, kernel 7.0.0-38-generic |
| NVIDIA driver | 615.71.09 |

The platform is old, but it barely matters. Every model in this write-up runs **entirely on the GPU**. The CPU, the
RAM speed and PCIe 3.0 only affect how fast a model loads from disk, and how fast MoE models run when some of their
weights spill into system RAM. The same GPU on a new platform would post nearly the same numbers.

The RAM runs at its fallback speed because XMP (ASUS calls it D.O.C.P.) is off in the BIOS. Turning it on is free.
It helps model loading and CPU-offloaded models, not the results below.

## 2. Software stack

```
clients (OpenCode, Hermes, curl, browser)
        │  OpenAI-compatible API, one key per client
        ▼
keygate          :8080      key → allowed models check, SQLite request log            keygate/
        ▼
llama-swap       127.0.0.1:8081   starts the requested model, stops the previous one
        ├──► llama-server (llama.cpp, CUDA)   LLMs at 128K context
        ├──► ComfyUI :8188                    FLUX.2 Klein images, Wan 2.2 video
        └──► Chatterbox                       text-to-speech and voice cloning
```

| Piece | Version | Role |
|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server` | 0.5.0-dev, commit `d89651a`, CUDA build | runs the LLMs |
| [llama-swap](https://github.com/mostlygeek/llama-swap) | v262 | model router; loads on demand, one model on the GPU at a time |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | v0.43.0, own venv, PyTorch for CUDA 13 | image and video |
| [Chatterbox](https://github.com/resemble-ai/chatterbox) | own venv, small FastAPI wrapper | `/v1/audio/speech` |
| keygate | this repo | per-key model permissions and usage log |

**Why swap instead of running everything at once?** At 128K context, a 30B-class LLM uses 18–24 GB. That is the
whole card. llama-swap gives one address to call, and whatever model a request names gets loaded, so
clients never need to know about ports or processes. A swap takes about 5–60 s depending on model size.

## 3. LLMs: what was tested and how

### The rules

- **128K context, fully on the GPU, or it doesn't count.** 96K was the minimum acceptable, and everything was
  run at `-c 131072`. Models that only fit by cutting context, or by spilling into system RAM, were left out.
  That ruled out Granite 4.2 30B, for example.
- Flash attention, one request slot, and a quantized KV cache (8-bit K, 8-bit or 4-bit V).
- The best quantization that still fits 128K on 24 GB: Q8 for the 8B model, Q4–Q5 for the 30B-class models.
- Each model card's recommended sampling settings.

### The three tests

1. **Speed.** Prompts of about 11K and 80K tokens, built from real C++ source, with the prompt cache off. Measured:
   prompt processing (prefill), generation speed, time to first token, VRAM.
2. **Coding.** Five tasks × 3 samples each: an LRU cache, a strict duration parser, an expression evaluator without
   `eval`, a deterministic topological sort, and a half-open interval set. Each answer is run against hidden unit
   tests. Thinking models get up to **32,768 output tokens**. An answer that hits the limit without code counts as a
   fail, logged separately as "no answer".
3. **Refusals.** Ten edgy but legitimate requests: a port scanner, how lock-picking works, a phishing example for
   security training, a keylogger for your own machine, a dark-comedy story, and so on. A keyword check catches
   outright refusals.

Full details and caveats: [bench/METHODOLOGY.md](bench/METHODOLOGY.md). Harness, tasks, raw results and every
failing answer: [bench/](bench/).

### Results

| Model | Coding | Prefill ~11K / ~80K (tok/s) | Gen ~11K / ~80K (tok/s) | First token @80K | VRAM @128K | Refused |
|---|:-:|--:|--:|--:|--:|:-:|
| **muse-glimmer-30b** | **15/15** | 3,303 / **2,964** | 43.5 / **38.9** | **25.5 s** | **18.5 GB** | 2/10 |
| **muse-glimmer-30b-heretic** | **15/15** | 3,250 / 2,913 | 42.0 / 37.7 | 26.0 s | 19.3 GB | 2/10 |
| gemma-4-31b (Google QAT) | **15/15** | 2,658 / 1,744 | 35.0 / 21.1 | 55.3 s | 22.7 GB | 0/10 |
| gemma-4-31b-unsloth | **15/15** | 2,248 / 1,541 | 34.2 / 20.8 | 62.6 s | 23.6 GB | 1/10 |
| gemma-4-31b-abl | **15/15** | 2,259 / 1,546 | 34.3 / 20.8 | 62.4 s | 23.4 GB | 3/10 |
| gemma-4-31b-hauhau | 13/15 | 2,255 / 1,546 | 34.3 / 20.8 | 62.4 s | 23.4 GB | 0/10 |
| granite-4.2-8b | 12/15 | 8,121 / 3,352 | **76.7** / 39.7 | 29.3 s | 20.0 GB | 1/10 |
| granite-4.2-8b-abl | 12/15 | **8,231** / 3,357 | **76.7** / 39.7 | 29.3 s | 20.0 GB | 0/10 |
| muse-glimmer-30b-abl | 12/15 | 3,260 / 2,910 | 42.0 / 37.6 | 26.2 s | 19.3 GB | 0/10 |
| qwen3.8-27b | 9/15 | 2,597 / 2,130 | 38.2 / 25.8 | 38.0 s | 22.0 GB | 1/10 |

The same "80K" text is a different number of tokens for each tokenizer: Glimmer 76K, Qwen 81K, Gemma 97K,
Granite 98K. Gemma and Granite do more work in that column.

### What the numbers say

- **Muse Glimmer 30B wins.** Its memory use is the reason. Only 13 of its 52 layers use full attention, with 2 KV
  heads, so its KV cache at 128K is tiny. That leaves the most headroom, and generation barely slows from 11K to
  80K tokens (43.5 → 38.9 tok/s). Every other 30B-class model loses 30–40% over the same range.
- **Gemma 4 31B codes just as well** (15/15 in three of four builds) but is the slowest at long context, and it only
  just fits. The Unsloth, abliterated and HauhauCS Q4_K builds needed `-ub 256` (a smaller prompt-processing batch)
  to fit 128K, costing about 11–15% of prefill speed. Google's own QAT Q4_0 file fits without it and is also the
  fastest Gemma.
- **Granite 4.2 8B is the sprinter.** It has about 2.5× the prefill and 2× the generation speed of the big models at
  short context. But it failed all three attempts at the expression-evaluator task by reasoning until it hit the
  32K-token limit.
- **Qwen3.8 27B came last (9/15).** Four of its six misses were runaway reasoning that never produced an answer.
- **Two different failure modes.** Runaway reasoning (Qwen, Granite) looks like a 20-minute stall in a coding agent.
  Wrong code (the Glimmer abliteration produced three *syntax errors*) looks like a bug. The first is worse for
  agents; the second suggests the uncensoring edit damaged the model.
- **Uncensoring can be free or can cost points.** Heretic Glimmer and two of three uncensored Gemmas kept perfect
  scores. The plain Glimmer abliteration and the Granite abliteration lost points. None of the stock models was
  heavily censored on these prompts anyway. Stock Gemma refused nothing, while one of its "abliterated" builds
  refused three.

**Caveats:** 15 coding samples per model, so 1–2 points is noise. These are short single-file tasks, with no tool
calling or multi-file work. Quantization differs by model. This was one run on one machine.

## 4. Image, video and voice

All three sit behind llama-swap like the LLMs, so asking for `comfyui` or `chatterbox` unloads whatever LLM is
loaded. Samples with prompts and timings: [samples/](samples/).

| | Model (license) | Output | Speed on the 4090 |
|---|---|---|---|
| Image | FLUX.2 Klein 4B, distilled (Apache 2.0) | 1024×1024, 4 steps | **2.0 s** warm, 23.7 s cold (start ComfyUI + load) |
| Video | Wan 2.2 TI2V-5B (Apache 2.0) | 1280×704, 24 fps, 49 frames (~2 s) | **~58 s** including the swap from FLUX |
| Voice | Chatterbox (MIT) | 24 kHz speech, voice cloning from a 5–10 s clip | 4.3 s of speech in **2.4 s**, ~3.8 GB VRAM |

- Images and video: `python3 comfy/comfy_run.py image "…"` or `… video "…" --seconds 3`. ComfyUI's own web UI
  works too.
- Speech: `POST /v1/audio/speech`, the same request format as OpenAI's.

Model files are the official Comfy-Org repackages ([dl-comfy-models.sh](dl-comfy-models.sh)).

## 5. Access control: keygate

llama-swap's API keys are all-or-nothing: any key can use every model, and the key list lives in plain text in its
config. I wanted keys like "this laptop gets the coding models" and "the tablet gets voice only".

**Options considered:**
- **LiteLLM** has per-key models, budgets and a dashboard. It was rejected because it needs Postgres and containers,
  updates weekly, and in **March 2026 two of its PyPI releases (1.82.7 and 1.82.8) shipped a credential-stealing
  backdoor** after a CI token leak. That's a lot of supply chain for a home server whose real requirement is "this key may use these
  models".
- **keygate**, a single Python file using only the standard library and SQLite. No `pip install`, so no third-party
  code to trust.

**What keygate does:**
- Takes port 8080. llama-swap moves to `127.0.0.1:8081` and keeps a single internal key, so nothing on the LAN can
  bypass the gate.
- Reads the model name from each request: the JSON body, the multipart form, or `/upstream/<model>/…` paths. It
  checks the name against the key's allowed list, which can include globs like `gemma-*` or `*`.
- Forwards allowed requests and streams the replies back. When a client disconnects, generation stops.
- Answers `GET /v1/models` with only the models that key may use.
- Blocks llama-swap's admin pages (logs, unload, UI) from the network.
- Logs every request to SQLite: key, client IP, model, status, duration and token counts. Prompts and replies are
  never stored.
- Stores keys only as **SHA-256 hashes**, so a key is shown once when created.

```bash
sudo keygate add "opencode laptop" --models muse-glimmer-30b-heretic,granite-4.2-8b
sudo keygate list
sudo keygate usage --days 30
```

Install and migration: [keygate/README.md](keygate/README.md).

## 6. Security notes

- **The API is on the LAN only.** Nothing is port-forwarded, and keygate speaks plain HTTP. Put a TLS reverse proxy
  in front before keys travel over an untrusted network.
- **ComfyUI's port 8188 has no authentication.** It is restricted with firewall rules on the router.
- **Secrets on disk are tightened down:**

  | File | Readable by |
  |---|---|
  | `/etc/llama-swap/config.yaml` | root and the `llama` service only (`640`) |
  | its backups | root only (`600`) |
  | `/etc/keygate/keygate.env` | root and the `keygate` service only (`640`) |
  | keygate's database (`/var/lib/keygate`) | the `keygate` service only (`700`) |

- **Both services run as their own unprivileged system users.** keygate's systemd unit adds `ProtectSystem=strict`,
  no capabilities and a restricted set of system calls.
- **No secrets in this repo.** Before each push the commit, the whole tree and the full history are checked for every
  real key on the server.
- **Skipped: a third-party "RTX 4000-series unlock" kernel module.** It was making the rounds that week. It is
  unsigned and runs in the kernel, a serious risk, and it offers nothing for llama.cpp workloads.

## 7. Lessons learned

- **Thinking models need a big output budget.** At a 16K-token cap, Qwen scored 2/15. Most answers were cut off
  mid-reasoning, not wrong. At 32K it scored 9/15. Always count "no answer" separately from "wrong answer".
- **Benchmarking a shared server needs an idle guard.** The first batch collided with a real client's requests. The
  harness now waits while any model is busy, and before swapping models it waits for 5 quiet minutes.
- **128K on 24 GB is a memory budget.** The KV cache dominates, so its quantization and the model's attention design
  decide whether a model fits. The compute buffer can be the last 1–2 GB, which is what `-ub 256` fixes.
- **Reload llama-swap by signalling its main process only.** `systemctl kill -s HUP` also hits its child processes
  and broke its GPU monitor.
- **`pkill -f` / `pgrep -f` match their own shell** when the pattern appears in the command line. Kill by exact PID.
- **Podman on Rocky 8 + firewalld:** a container could accept connections but not reach out. DNS failed with "Host
  is unreachable", and Forgejo reported GitHub as a "disallowed host". Fix: put `cni-podman0` in firewalld's
  `trusted` zone.

## 8. Upgrade path

These are notes from planning a second GPU (an RTX 3080 Ti 12 GB). Prices are as of November 2026.

- **A 12 GB second card is useful.** Chatterbox needs ~3.8 GB and FLUX.2 Klein fits comfortably, so voice and images
  could stay loaded beside an LLM on the 4090.
- **Case:** Phanteks Enthoo Pro 2 Server Edition (PH-ES620PC_BK02). It has 11 expansion slots and 503 mm of GPU
  clearance for about $175. The Enthoo Elite costs about $200 more for looks, not capability.
- **Platform:** DDR5 is expensive (about $1,300 for 64 GB), so keeping this DDR4 platform is sensible for now. On
  the Z370, a second GPU means sharing the CPU's 16 lanes as x8/x8.
  - For a new build, AM5 with a Ryzen 9 9900X or 9950X is the pick. X3D chips buy gaming cache, which doesn't help
    inference.
  - Pair it with an X870E board that splits the CPU lanes x8/x8, such as an ASUS ProArt. On B850 boards the second
    long slot hangs off the chipset at x4.
- **Bigger:** a used EPYC system (ASRock Rack ROMED8-2T, EPYC 7532, 8 × 32 GB RDIMM) gives 128 PCIe 4.0 lanes and
  eight memory channels for about $2,750–3,700.

## 9. Repo map

| Path | What |
|---|---|
| [bench/](bench/) | Benchmark harness, coding tasks, model configs, raw results, failing answers, methodology |
| [samples/](samples/) | Unedited image, video and voice outputs |
| [keygate/](keygate/) | Per-key model permissions proxy, installer, systemd unit |
| [comfy/](comfy/), [install-comfyui.sh](install-comfyui.sh), [dl-comfy-models.sh](dl-comfy-models.sh) | Image and video stack |
| [tts/](tts/) | Chatterbox install and API server |
| [llama-swap-media.yaml](llama-swap-media.yaml) | llama-swap entries for ComfyUI and Chatterbox |
| [dl-eval-batch.sh](dl-eval-batch.sh) | Downloads the benchmarked GGUFs |
