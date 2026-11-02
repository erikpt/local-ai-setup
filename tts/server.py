#!/usr/bin/env python3
"""Minimal OpenAI-compatible TTS server for Chatterbox (MIT, ResembleAI).

POST /v1/audio/speech  {"input": "...", "voice": "<name>" , "exaggeration": 0.5, "cfg_weight": 0.5}
  -> audio/wav.  "voice" picks a reference clip voices/<name>.wav for cloning; omit for the default voice.
GET  /health, GET /v1/models
Run: python server.py --port 5890 --voices /models/chatterbox/voices
"""
import argparse, io, pathlib, wave

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from chatterbox.tts import ChatterboxTTS

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=5890)
ap.add_argument("--voices", default="/models/chatterbox/voices")
args = ap.parse_args()

VOICES = pathlib.Path(args.voices)
model = ChatterboxTTS.from_pretrained(device="cuda")
app = FastAPI()


class Speech(BaseModel):
    input: str
    model: str = "chatterbox"
    voice: str | None = None
    exaggeration: float = 0.5
    cfg_weight: float = 0.5


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": "chatterbox", "object": "model"}]}


@app.post("/v1/audio/speech")
def speech(req: Speech):
    if not req.input.strip():
        raise HTTPException(400, "empty input")
    ref = None
    if req.voice and req.voice not in ("default", "alloy"):
        ref = VOICES / f"{pathlib.Path(req.voice).name}.wav"  # .name blocks path traversal
        if not ref.is_file():
            raise HTTPException(404, f"no voice clip {ref.name} in {VOICES}")
    wav = model.generate(req.input, audio_prompt_path=str(ref) if ref else None,
                         exaggeration=req.exaggeration, cfg_weight=req.cfg_weight)
    # 16-bit PCM WAV via the stdlib (torchaudio.save now needs the separate torchcodec package)
    pcm = (wav.squeeze(0).clamp(-1, 1).cpu().numpy() * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(model.sr)
        w.writeframes(pcm)
    return Response(buf.getvalue(), media_type="audio/wav")


if __name__ == "__main__":
    uvicorn.run(app, host=args.host, port=args.port)
