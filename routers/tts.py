import os
import io
import uuid
import struct
import asyncio
from fastapi import APIRouter, Request, HTTPException
from database import get_db_connection
from security import get_current_user
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

try:
  import soundfile as sf
  import numpy as np
  from kokoro_onnx import Kokoro
except ImportError:
  sf = None
  np = None
  Kokoro = None

try:
  import edge_tts
except ImportError:
  edge_tts = None

router = APIRouter()

# The global kokoro instance
kokoro_model = None
tts_cache = {}

class TTSRequest(BaseModel):
  text: str
  voice: str | None = None
  engine: str | None = None

VOICE_MAP_EDGE = {
  "af_bella": "en-US-JennyNeural",
  "af_sarah": "en-US-AriaNeural",
  "am_adam": "en-US-GuyNeural",
  "am_michael": "en-US-ChristopherNeural"
}

def init_kokoro(model_path: str, voices_path: str):
  global kokoro_model
  if Kokoro is None:
    print("kokoro_onnx is not installed")
    return
  try:
    # Ensure CPU provider is used (avoids DirectML / GPU crashes on Windows & Linux)
    os.environ.setdefault("ONNX_PROVIDER", "CPUExecutionProvider")

    # For modern kokoro-onnx (>=0.5.0), voices.bin is required (loaded via np.load)
    bin_path = voices_path.replace(".json", ".bin") if voices_path.endswith(".json") else voices_path
    if os.path.exists(bin_path):
      try:
        kokoro_model = Kokoro(model_path, bin_path)
        print(f"Kokoro loaded successfully from {model_path} with {bin_path}")
        return
      except Exception as e_bin:
        print(f"Failed to load Kokoro with bin ({e_bin}), trying json fallback...")

    # Fallback for older kokoro-onnx versions that use voices.json
    json_path = voices_path.replace(".bin", ".json") if voices_path.endswith(".bin") else voices_path
    if os.path.exists(json_path):
      kokoro_model = Kokoro(model_path, json_path)
      print(f"Kokoro loaded successfully from {model_path} with {json_path}")
      return

    print(f"Warning: Neither {bin_path} nor {json_path} exists for Kokoro.")
  except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"Failed to load Kokoro: {e}")

def generate_wav_header(sample_rate, num_channels=1, bit_depth=16):
  header = b'RIFF'
  header += struct.pack('<I', 0xFFFFFFFF)
  header += b'WAVE'
  header += b'fmt '
  header += struct.pack('<I', 16)
  header += struct.pack('<H', 1)
  header += struct.pack('<H', num_channels)
  header += struct.pack('<I', sample_rate)
  byte_rate = sample_rate * num_channels * (bit_depth // 8)
  header += struct.pack('<I', byte_rate)
  block_align = num_channels * (bit_depth // 8)
  header += struct.pack('<H', block_align)
  header += struct.pack('<H', bit_depth)
  header += b'data'
  header += struct.pack('<I', 0xFFFFFFFF)
  return header

def get_user_tts_prefs(request: Request, engine_override: str = None, voice_override: str = None, user: dict = None):
  engine_to_use = engine_override
  voice_to_use = voice_override
  if not engine_to_use or not voice_to_use:
    try:
      if user is None:
        conn = get_db_connection()
        try:
          user = get_current_user(request, conn)
        finally:
          conn.close()
      if user:
        is_parent = user.get("is_parent")
        if not voice_to_use:
          voice_to_use = (user.get("parent_tts_voice") if is_parent else None) or user.get("tts_voice")
        if not engine_to_use:
          engine_to_use = (user.get("parent_tts_engine") if is_parent else None) or user.get("tts_engine")
    except Exception:
      pass
      
  if not voice_to_use:
    voice_to_use = "af_bella"
  if not engine_to_use:
    engine_to_use = "kokoro"
    
  return engine_to_use, voice_to_use

from fastapi.responses import Response

SUBSCRIPT_MAP = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁺⁻", "0123456789+-")

def clean_tts_text(raw: str) -> str:
  if not raw:
    return ""
  import re
  t = str(raw).translate(SUBSCRIPT_MAP)
  t = re.sub(r"\[(?:emotion|draw|DRAW_STEPS|DRAW_DIAGRAM|DRAW):[^\]]*\]", " ", t, flags=re.IGNORECASE)
  t = t.replace("→", " gives ").replace("->", " gives ").replace("—", ", ").replace("–", ", ")
  t = re.sub(r"[*_#`~]+", "", t)
  t = re.sub(r"\bCO2\b", "C O 2", t)
  t = re.sub(r"\bO2\b", "O 2", t)
  t = re.sub(r"\bH2O\b", "H 2 O", t)
  t = re.sub(r"\s+", " ", t).strip()
  return t[:2000]

async def synthesize_audio_bytes(text: str, engine: str, voice: str) -> tuple[bytes, str]:
  cleaned = clean_tts_text(text)
  if not cleaned:
    cleaned = " Ready."

  engines_to_try = [engine]
  if engine == "kokoro" and edge_tts is not None:
    engines_to_try.append("edge-tts")
  elif engine == "edge-tts" and kokoro_model is not None:
    engines_to_try.append("kokoro")

  last_err = None
  for eng in engines_to_try:
    try:
      if eng == "kokoro" and kokoro_model is not None:
        samples, sample_rate = await asyncio.to_thread(
          kokoro_model.create, cleaned, voice=voice or "af_bella", speed=1.0, lang="en-us"
        )
        byte_io = io.BytesIO()
        sf.write(byte_io, samples, sample_rate, format="WAV")
        return byte_io.getvalue(), "audio/wav"
      elif eng == "edge-tts" and edge_tts is not None:
        edge_voice = VOICE_MAP_EDGE.get(voice or "af_bella", "en-US-JennyNeural")
        audio_data = bytearray()
        communicate = edge_tts.Communicate(cleaned, edge_voice)
        async for chunk in communicate.stream():
          if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
        if len(audio_data) > 0:
          return bytes(audio_data), "audio/mpeg"
    except Exception as e:
      last_err = e
      print(f"TTS engine {eng} failed, trying fallback if available: {e}")

  raise HTTPException(status_code=500, detail=f"TTS generation failed: {last_err}")

@router.post("/api/tts/prepare")
async def prepare_tts(req: TTSRequest, request: Request):
  conn = get_db_connection()
  try:
    user = get_current_user(request, conn)
    if not user:
      raise HTTPException(status_code=401, detail="Authentication required")
  finally:
    conn.close()
  if not req.text:
    raise HTTPException(status_code=400, detail="Text is required")
    
  engine_to_use, voice_to_use = get_user_tts_prefs(request, req.engine, req.voice, user=user)
  
  if engine_to_use == "kokoro":
    if kokoro_model is None:
      if edge_tts is not None:
        engine_to_use = "edge-tts"
      else:
        raise HTTPException(status_code=503, detail="Local Voice Engine not initialized")
  elif engine_to_use == "edge-tts":
    if edge_tts is None:
      if kokoro_model is not None:
        engine_to_use = "kokoro"
      else:
        raise HTTPException(status_code=503, detail="Cloud Fast Voice Engine not initialized")
    
  if len(tts_cache) > 200:
    oldest_key = next(iter(tts_cache))
    tts_cache.pop(oldest_key, None)

  audio_id = str(uuid.uuid4())
  tts_cache[audio_id] = {"text": clean_tts_text(req.text), "voice": voice_to_use, "engine": engine_to_use}
  return {"audio_id": audio_id}

@router.get("/api/tts/stream/{audio_id}")
async def stream_tts(audio_id: str, request: Request):
  conn = get_db_connection()
  try:
    if not get_current_user(request, conn):
      raise HTTPException(status_code=401, detail="Authentication required")
  finally:
    conn.close()
  data = tts_cache.get(audio_id)
  if not data:
    raise HTTPException(404, "Audio not found")
    
  text = data["text"]
  voice = data["voice"]
  engine = data.get("engine", "kokoro")
  audio_bytes, media_type = await synthesize_audio_bytes(text, engine, voice)
  return Response(
    content=audio_bytes,
    media_type=media_type,
    headers={
      "Content-Length": str(len(audio_bytes)),
      "Accept-Ranges": "bytes",
      "Cache-Control": "no-store"
    }
  )

@router.post("/api/tts")
async def text_to_speech(req: TTSRequest, request: Request):
  conn = get_db_connection()
  try:
    user = get_current_user(request, conn)
    if not user:
      raise HTTPException(status_code=401, detail="Authentication required")
  finally:
    conn.close()
  if not req.text:
    raise HTTPException(status_code=400, detail="Text is required")
    
  engine_to_use, voice_to_use = get_user_tts_prefs(request, req.engine, req.voice, user=user)
  audio_bytes, media_type = await synthesize_audio_bytes(req.text, engine_to_use, voice_to_use)
  return Response(
    content=audio_bytes,
    media_type=media_type,
    headers={
      "Content-Length": str(len(audio_bytes)),
      "Accept-Ranges": "bytes",
      "Cache-Control": "no-store"
    }
  )

@router.post("/tts/generate")
async def text_to_speech_form_compat(request: Request):
  """Compatibility endpoint accepting either FormData (text=...) or JSON."""
  text_val = ""
  content_type = request.headers.get("content-type", "")
  if "application/json" in content_type:
    body = await request.json()
    text_val = (body.get("text") or "").strip()
  else:
    form = await request.form()
    text_val = str(form.get("text") or "").strip()
  return await text_to_speech(TTSRequest(text=text_val), request)


