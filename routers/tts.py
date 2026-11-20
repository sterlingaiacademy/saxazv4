from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from collections import OrderedDict
import asyncio
import base64
import io
import json
import os
import re
import struct
import time
import uuid
import wave
import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

router = APIRouter(prefix="/api/tts", tags=["tts"])

GEMINI_TTS_MODEL = "gemini-3.8-flash-tts"
GEMINI_TTS_FALLBACK_MODEL = "gemini-3.8-flash-lite-tts"
GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_API_REVISION = "2026-05-20"

# Four expressive, child-friendly personas mapped to Google Gemini 3.8 Flash TTS studio voices
PERSONA_CONFIG = {
    "af_bella": {
        "id": "af_bella",
        "short_id": "bella",
        "name": "Bella",
        "role": "The Biologist",
        "gemini_voice": "Aoede",
        "voice_cue": "Warm, bubbly, caring biology teacher speaking with a bright natural smile.",
        "preview_text": "Hey there, superstar! I'm Bella, your biology buddy! Ready to explore how amazing living things work together?",
    },
    "af_sarah": {
        "id": "af_sarah",
        "short_id": "sarah",
        "name": "Sarah",
        "role": "The Scientist",
        "gemini_voice": "Leda",
        "voice_cue": "Youthful, cheerful, curious science guide full of friendly wonder.",
        "preview_text": "Hi friend! I'm Sarah, your science explorer! Whenever something looks tricky, we'll turn it into a super fun story together!",
    },
    "am_adam": {
        "id": "am_adam",
        "short_id": "adam",
        "name": "Adam",
        "role": "The Astronaut",
        "gemini_voice": "Puck",
        "voice_cue": "Upbeat, warm, adventurous big-brother mentor with an encouraging grin.",
        "preview_text": "Hey co-pilot! I'm Adam! Buckle up -- we're going to make every chapter feel like an awesome adventure!",
    },
    "am_michael": {
        "id": "am_michael",
        "short_id": "michael",
        "name": "Michael",
        "role": "The Mathematician",
        "gemini_voice": "Achird",
        "voice_cue": "Kind, friendly, reassuring coach with gentle warmth and clarity.",
        "preview_text": "Hey buddy! I'm Michael! Step by step, we'll crack every puzzle together and have fun doing it!",
    },
}

EMOTION_CUES = {
    "friendly_greeting": "Welcoming, joyful, and warm with lively rising melody and natural breath pauses.",
    "curious_question": "Playfully intrigued and curious with an upbeat questioning lilt and warm smile.",
    "empathetic_buddy": "Gentle, comforting, and reassuring with soft supportive warmth and unhurried pauses.",
    "excited_progress": "Beaming with pride and upbeat excitement, lively pitch lift, and warm encouragement.",
    "memory_trick": "Animated storyteller full of wonder, expressive musical cadence, and vivid phrasing.",
    "teaching": "Cheerful, warm, and conversational human teacher with clear expressive phrasing.",
    "encouraging_retry": "Upbeat, playful, and motivating with friendly cheering enthusiasm.",
    "celebrating": "Joyful, delighted, and celebratory with sparkling proud energy and bright smile.",
    "gentle_reminder": "Warm, friendly, and lightly playful with a kind smiling nudge and relaxed pacing.",
}

INSTANT_EXAM_OPENERS = {
    "wrong_opener": (
        "Hey buddy -- no worries at all on that one! Let's look at a super fun way to picture how this works.",
        "empathetic_buddy",
    ),
    "partial_opener": (
        "Ooh, nice work buddy! You already got part of it! Let's grab the one missing piece for full marks.",
        "excited_progress",
    ),
    "retry_cta": (
        "Now that you know the secret trick, hit Try Again right below and show it off -- you've got this!",
        "encouraging_retry",
    ),
    "correct_opener": (
        "Woohoo -- spot on, superstar! You nailed every single point! Let's jump to the next one!",
        "celebrating",
    ),
}

VOICE_ALIASES = {
    "af_bella": "af_bella",
    "bella": "af_bella",
    "af_sarah": "af_sarah",
    "sarah": "af_sarah",
    "am_adam": "am_adam",
    "adam": "am_adam",
    "am_michael": "am_michael",
    "michael": "am_michael",
}

_SCRIPT_LANG_PATTERNS = [
    (re.compile(r"[\u0D00-\u0D7F]"), "Malayalam"),
    (re.compile(r"[\u0900-\u097F]"), "Hindi"),
    (re.compile(r"[\u0B80-\u0BFF]"), "Tamil"),
    (re.compile(r"[\u0600-\u06FF]"), "Arabic"),
]

# Allowed native Gemini 3.8 TTS point-in-time human vocal tags
_ALLOWED_VOCAL_TAGS_RE = re.compile(
    r"<(?!/?(?:laugh|sigh|cough|breath|short pause|gasp|throat-clearing)\b)[^>]*>",
    flags=re.IGNORECASE,
)


class GeminiTTSUpstreamError(Exception):
    def __init__(self, status_code: int, message: str, error_code: str = "gemini_tts_error"):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.error_code = error_code


tts_cache: dict[str, dict] = {}

# LRU cache: (fmt, voice_key, emo_key, pace_bucket, text) -> (audio_bytes, media_type, model_used, timestamp)
_AUDIO_LRU_CACHE: OrderedDict[tuple[str, str, str, str, str], tuple[bytes, str, str, float]] = OrderedDict()
_AUDIO_LRU_MAX_ITEMS = 250

_INFLIGHT_TASKS: dict[tuple[str, str, str, str, str], asyncio.Task] = {}

_http_client: httpx.AsyncClient | None = None
_http_client_loop = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client, _http_client_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None
    if _http_client is None or _http_client.is_closed or _http_client_loop is not current_loop:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(26.0, connect=6.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
        )
        _http_client_loop = current_loop
    return _http_client


def _get_gemini_api_key() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


def _normalize_voice_key(voice: str | None) -> str:
    if not voice:
        return "af_bella"
    return VOICE_ALIASES.get(voice.strip().lower(), "af_bella")


def _normalize_engine(engine: str | None = None) -> str:
    return "gemini"


def _pace_bucket(speed: float) -> str:
    s = float(speed or 1.0)
    if s <= 0.94:
        return "slow"
    if s >= 1.08:
        return "brisk"
    return "normal"


def _resolve_user_tts_prefs(request: Request, req_voice: str | None, req_engine: str | None = None) -> tuple[str, str]:
    voice = req_voice
    if not voice:
        try:
            from database import get_db_connection
            from security import get_current_user
            conn = get_db_connection()
            try:
                user = get_current_user(request, conn)
                if user:
                    if user.get("is_parent"):
                        voice = user.get("parent_tts_voice") or user.get("tts_voice") or "af_bella"
                    else:
                        voice = user.get("tts_voice") or "af_bella"
            finally:
                conn.close()
        except Exception:
            pass
    return _normalize_voice_key(voice), "gemini"


def clean_tts_text(raw: str) -> str:
    """
    Strip UI control tags, arbitrary HTML tags, markdown, and emojis while preserving
    valid Gemini 3.8 TTS inline vocal tags (`<laugh>`, `<sigh>`, `<short pause>`, `<breath>`, `<gasp>`)
    and all multilingual Unicode scripts (Malayalam, Hindi, Tamil, Arabic, English).
    """
    if not raw:
        return ""
    text = raw
    text = re.sub(
        r"\[(draw|emotion|board|action|sound|anim|quiz|video|topic|exams|history|scroll|retry|question|navigate)[^\]]*\]",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = _ALLOWED_VOCAL_TAGS_RE.sub(" ", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"[*_~#|]+", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", " and ")
        .replace("&middot;", ", ")
        .replace("&bull;", ", ")
        .replace("&rarr;", " yields ")
        .replace("&mdash;", " -- ")
    )
    text = re.sub(r"[•●▪▸►─━═→←]+", " ", text)
    text = re.sub(
        r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]+",
        " ",
        text,
    )
    text = re.sub(
        r"\b(?:ha\s*ha+|he\s*he+|ho\s*ho+)\b[!,\.\s—\-]*",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def detect_script_language(text: str) -> str | None:
    """Detect Malayalam, Hindi, Tamil, or Arabic Unicode script in `text`."""
    if not text:
        return None
    for regex, lang_name in _SCRIPT_LANG_PATTERNS:
        if regex.search(text):
            return lang_name
    return None


def _infer_emotion_key(emotion: str | None, text: str = "") -> str:
    emo_key = (emotion or "").strip().lower()
    alias_map = {
        "laughing": "friendly_greeting",
        "talking": "teaching",
        "thinking": "curious_question",
        "serious": "empathetic_buddy",
        "base": "teaching",
        "excited": "celebrating",
        "happy": "celebrating",
        "curious": "curious_question",
        "greeting": "friendly_greeting",
    }
    if emo_key in alias_map:
        emo_key = alias_map[emo_key]
    if emo_key in EMOTION_CUES:
        return emo_key

    low_txt = (text or "").lower()
    if any(k in low_txt for k in ("spot on", "full marks", "nailed", "superstar", "woohoo", "awesome job", "well done")):
        return "celebrating"
    if any(k in low_txt for k in ("hey ", "hello ", "welcome", "hi friend", "hi there")):
        return "friendly_greeting"
    if any(k in low_txt for k in ("no worries", "totally fair", "no stress", "from scratch", "don't worry")):
        return "empathetic_buddy"
    if any(k in low_txt for k in ("imagine", "picture", "think of", "secret", "trick", "like a team", "story")):
        return "memory_trick"
    if any(k in low_txt for k in ("try again", "another shot", "another try", "you've got this")):
        return "encouraging_retry"
    if "?" in low_txt[:120] or any(k in low_txt for k in ("do you know", "why do", "how is", "what happens")):
        return "curious_question"
    return "teaching"


def build_tts_instructions(voice_key: str, emo_key: str, text: str = "", speed: float = 1.0) -> str:
    """
    Build structured `speech_metadata.style` acting direction for Gemini 3.8 Flash TTS
    with natural storytelling pace and native multilingual prosody when Indic/Arabic scripts appear.
    """
    persona = PERSONA_CONFIG.get(voice_key, PERSONA_CONFIG["af_bella"])
    emo_cue = EMOTION_CUES.get(emo_key, EMOTION_CUES["teaching"])
    pace = _pace_bucket(speed)
    pace_str = ""
    if pace == "slow":
        pace_str = " Speak at a calm, unhurried, easy-to-follow storytelling pace with gentle natural pauses."
    elif pace == "brisk":
        pace_str = " Speak with brisk, lively energy."
    script_lang = detect_script_language(text)
    if script_lang:
        return f"{persona['voice_cue']} {emo_cue}{pace_str} Speak natural native {script_lang} while pronouncing English science terms clearly."
    return f"{persona['voice_cue']} {emo_cue}{pace_str}"


def _wrap_pcm16_as_wav(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    even_len = len(pcm_bytes) & ~1
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes[:even_len])
    return buf.getvalue()


def _extract_pcm_from_wav(wav_bytes: bytes) -> bytes | None:
    if len(wav_bytes) < 48 or wav_bytes[:4] != b"RIFF":
        return None
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            if wf.getnchannels() == 1 and wf.getsampwidth() == 2 and wf.getframerate() == 24000:
                return wf.readframes(wf.getnframes())
    except Exception:
        pass
    return None


def _ensure_wav_bytes(raw_bytes: bytes, sample_rate: int = 24000) -> bytes:
    if len(raw_bytes) >= 44 and raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WAVE":
        return raw_bytes
    return _wrap_pcm16_as_wav(raw_bytes, sample_rate)


def _classify_gemini_http_error(status_code: int, raw_body: str) -> GeminiTTSUpstreamError:
    low = (raw_body or "").lower()
    if status_code in (402, 429) and (
        "credit balance" in low
        or "billing" in low
        or "prepay credits" in low
        or "quota exceeded for metric" in low and "limit: 0" in low
    ):
        return GeminiTTSUpstreamError(
            status_code=402,
            message="Gemini API credits are depleted. Add credits in Google AI Studio Billing.",
            error_code="gemini_credits_depleted",
        )
    if status_code in (400, 401, 403) and ("api key not valid" in low or "api_key_invalid" in low or "permission_denied" in low):
        return GeminiTTSUpstreamError(
            status_code=503,
            message="GEMINI_API_KEY is invalid or unauthorized for Gemini 3.8 TTS.",
            error_code="gemini_invalid_key",
        )
    if status_code == 429:
        return GeminiTTSUpstreamError(
            status_code=429,
            message="Gemini 3.8 TTS rate limit reached (HTTP 429).",
            error_code="gemini_rate_limited",
        )
    return GeminiTTSUpstreamError(
        status_code=503,
        message=f"Gemini 3.8 TTS error ({status_code}): {(raw_body or '')[:180]}",
        error_code="gemini_upstream_error",
    )


def _store_in_lru(cache_key: tuple[str, str, str, str, str], audio_bytes: bytes, media_type: str, model_used: str) -> None:
    _AUDIO_LRU_CACHE[cache_key] = (audio_bytes, media_type, model_used, time.time())
    _AUDIO_LRU_CACHE.move_to_end(cache_key)
    while len(_AUDIO_LRU_CACHE) > _AUDIO_LRU_MAX_ITEMS:
        _AUDIO_LRU_CACHE.popitem(last=False)


def _build_interactions_payload(model_name: str, text: str, voice_key: str, emo_key: str, speed: float, stream: bool) -> dict:
    persona = PERSONA_CONFIG.get(voice_key, PERSONA_CONFIG["af_bella"])
    style_instructions = build_tts_instructions(voice_key, emo_key, text, speed)
    payload: dict = {
        "model": model_name,
        "input": [
            {
                "type": "user_input",
                "content": [
                    {
                        "type": "text",
                        "text": text,
                        "annotations": [
                            {
                                "type": "speech_metadata",
                                "style": style_instructions,
                            }
                        ],
                    }
                ],
            }
        ],
        "response_format": {"type": "audio"},
        "generation_config": {
            "speech_config": [
                {"voice": persona["gemini_voice"]},
            ]
        },
        "store": False,
    }
    if stream:
        payload["stream"] = True
    return payload


async def _stream_gemini_pcm_chunks(text: str, voice_key: str, emo_key: str, speed: float = 1.0):
    """
    Streams raw 24kHz 16-bit signed little-endian mono PCM (`audio/l16`) chunks directly from
    Google Gemini 3.8 Flash TTS (`gemini-3.8-flash-tts`) via the Interactions API SSE stream,
    with automatic fallback to `gemini-3.8-flash-lite-tts` on transient rate limits / 5xx errors.
    """
    api_key = _get_gemini_api_key()
    if not api_key:
        raise GeminiTTSUpstreamError(status_code=503, message="GEMINI_API_KEY is not configured.", error_code="gemini_missing_key")

    client = _get_http_client()
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
        "Api-Revision": GEMINI_API_REVISION,
    }

    last_err: GeminiTTSUpstreamError | None = None
    models_to_try = (GEMINI_TTS_MODEL, GEMINI_TTS_FALLBACK_MODEL)

    for idx, model_name in enumerate(models_to_try):
        payload = _build_interactions_payload(model_name, text, voice_key, emo_key, speed, stream=True)
        yielded_any = False
        carry_byte = b""
        try:
            async with client.stream(
                "POST",
                f"{GEMINI_INTERACTIONS_URL}?alt=sse",
                headers=headers,
                json=payload,
                timeout=26.0,
            ) as resp:
                if resp.status_code != 200:
                    err_body = (await resp.aread()).decode("utf-8", errors="ignore")
                    gem_err = _classify_gemini_http_error(resp.status_code, err_body)
                    last_err = gem_err
                    if gem_err.status_code == 402 or gem_err.error_code == "gemini_invalid_key" or idx == len(models_to_try) - 1:
                        raise gem_err
                    continue

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    s_line = line.strip()
                    if not s_line.startswith("data:"):
                        continue
                    data_str = s_line[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        ev = json.loads(data_str)
                    except Exception:
                        continue
                    et = ev.get("event_type")
                    if et == "step.delta":
                        delta = ev.get("delta") or {}
                        if delta.get("type") == "audio" and delta.get("data"):
                            raw_chunk = carry_byte + base64.b64decode(delta["data"])
                            if len(raw_chunk) % 2 == 1:
                                carry_byte = raw_chunk[-1:]
                                raw_chunk = raw_chunk[:-1]
                            else:
                                carry_byte = b""
                            if raw_chunk:
                                yielded_any = True
                                yield raw_chunk, model_name
                    elif et in ("error", "interaction.failed"):
                        err_msg = json.dumps(ev)[:180]
                        raise GeminiTTSUpstreamError(503, f"Gemini TTS stream failed: {err_msg}", "gemini_stream_failed")

                if yielded_any:
                    return
                last_err = GeminiTTSUpstreamError(503, f"Empty audio stream from {model_name}", "gemini_empty_stream")
        except GeminiTTSUpstreamError as g_err:
            last_err = g_err
            if yielded_any or g_err.status_code == 402 or g_err.error_code == "gemini_invalid_key" or idx == len(models_to_try) - 1:
                raise
        except Exception as exc:
            last_err = GeminiTTSUpstreamError(503, f"Gemini 3.8 TTS connection error: {exc}", "gemini_network_error")
            if yielded_any or idx == len(models_to_try) - 1:
                raise last_err

    if last_err:
        raise last_err


async def _synthesize_gemini_wav(text: str, voice_key: str, emo_key: str, speed: float = 1.0) -> tuple[bytes, str, str]:
    """
    Synthesize studio-grade 24kHz WAV (`audio/wav`) via Google Gemini 3.8 Flash TTS (`gemini-3.8-flash-tts`),
    falling back to `gemini-3.8-flash-lite-tts` on transient 429/503.
    """
    api_key = _get_gemini_api_key()
    if not api_key:
        raise GeminiTTSUpstreamError(status_code=503, message="GEMINI_API_KEY is not configured.", error_code="gemini_missing_key")

    pace = _pace_bucket(speed)
    pcm_cache_key = ("pcm", voice_key, emo_key, pace, text)
    cached_pcm = _AUDIO_LRU_CACHE.get(pcm_cache_key)
    if cached_pcm and len(cached_pcm[0]) >= 4:
        _AUDIO_LRU_CACHE.move_to_end(pcm_cache_key)
        wav_from_pcm = _wrap_pcm16_as_wav(cached_pcm[0], 24000)
        return wav_from_pcm, "audio/wav", cached_pcm[2]

    client = _get_http_client()
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
        "Api-Revision": GEMINI_API_REVISION,
    }

    last_err: GeminiTTSUpstreamError | None = None
    models_to_try = (GEMINI_TTS_MODEL, GEMINI_TTS_FALLBACK_MODEL)

    for idx, model_name in enumerate(models_to_try):
        payload = _build_interactions_payload(model_name, text, voice_key, emo_key, speed, stream=False)
        resp = await client.post(
            GEMINI_INTERACTIONS_URL,
            headers=headers,
            json=payload,
            timeout=26.0,
        )
        if resp.status_code != 200:
            gem_err = _classify_gemini_http_error(resp.status_code, resp.text)
            last_err = gem_err
            if gem_err.status_code == 402 or gem_err.error_code == "gemini_invalid_key" or idx == len(models_to_try) - 1:
                raise gem_err
            continue

        data = resp.json()
        audio_b64 = None
        for step in reversed(data.get("steps") or []):
            if step.get("type") == "model_output":
                for item in reversed(step.get("content") or []):
                    if item.get("type") == "audio" and item.get("data"):
                        audio_b64 = item["data"]
                        break
            if audio_b64:
                break

        if not audio_b64:
            last_err = GeminiTTSUpstreamError(503, f"{model_name} returned no audio block.", "gemini_empty_audio")
            if idx == len(models_to_try) - 1:
                raise last_err
            continue

        raw_bytes = base64.b64decode(audio_b64)
        wav_bytes = _ensure_wav_bytes(raw_bytes, 24000)
        extracted_pcm = _extract_pcm_from_wav(wav_bytes)
        if extracted_pcm and len(extracted_pcm) >= 4:
            _store_in_lru(pcm_cache_key, extracted_pcm, "application/octet-stream", model_name)
        return wav_bytes, "audio/wav", model_name

    raise last_err or GeminiTTSUpstreamError(503, "Gemini 3.8 TTS failed to synthesize audio.", "gemini_tts_failed")


async def _get_or_create_wav_task(
    text: str, voice_key: str, speed: float, emotion: str | None = None
) -> tuple[bytes, str, str]:
    emo_key = _infer_emotion_key(emotion, text)
    pace = _pace_bucket(speed)
    cache_key = ("wav", voice_key, emo_key, pace, text)
    cached = _AUDIO_LRU_CACHE.get(cache_key)
    if cached:
        _AUDIO_LRU_CACHE.move_to_end(cache_key)
        return cached[0], cached[1], cached[2]

    inflight = _INFLIGHT_TASKS.get(cache_key)
    if inflight and not inflight.done():
        return await asyncio.shield(inflight)

    async def _run() -> tuple[bytes, str, str]:
        audio_bytes, media_type, model_used = await _synthesize_gemini_wav(text, voice_key, emo_key, speed)
        _store_in_lru(cache_key, audio_bytes, media_type, model_used)
        return audio_bytes, media_type, model_used

    task = asyncio.create_task(_run())
    _INFLIGHT_TASKS[cache_key] = task
    try:
        return await asyncio.shield(task)
    finally:
        if _INFLIGHT_TASKS.get(cache_key) is task:
            _INFLIGHT_TASKS.pop(cache_key, None)


def _cleanup_expired_sessions() -> None:
    now = time.time()
    expired = [k for k, v in tts_cache.items() if now - v.get("created_at", 0) > 900]
    for k in expired:
        tts_cache.pop(k, None)


_MAX_TTS_CHARS = 1200


def _require_tts_session(request: Request) -> dict:
    """Block unauthenticated external bots/scripts from draining Gemini TTS credits."""
    from database import get_db_connection
    from security import get_current_user
    conn = get_db_connection()
    try:
        user = get_current_user(request, conn)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required for voice synthesis.")
        return user
    finally:
        conn.close()


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None
    speed: float = 1.0
    engine: str | None = None
    emotion: str | None = None


@router.post("/prepare")
async def prepare_tts(req: TTSRequest, request: Request):
    _require_tts_session(request)
    cleaned = clean_tts_text(req.text)
    if not cleaned:
        raise HTTPException(status_code=400, detail="Empty text after cleaning")
    if len(cleaned) > _MAX_TTS_CHARS:
        cleaned = cleaned[:_MAX_TTS_CHARS]

    voice_key, engine = _resolve_user_tts_prefs(request, req.voice, req.engine)
    speed = max(0.5, min(2.0, float(req.speed or 1.0)))
    emo_key = _infer_emotion_key(req.emotion, cleaned)
    pace = _pace_bucket(speed)

    _cleanup_expired_sessions()

    audio_id = str(uuid.uuid4())
    cache_key = ("wav", voice_key, emo_key, pace, cleaned)
    cached = _AUDIO_LRU_CACHE.get(cache_key)

    if cached:
        tts_cache[audio_id] = {
            "text": cleaned,
            "voice": voice_key,
            "speed": speed,
            "engine": engine,
            "emotion": emo_key,
            "created_at": time.time(),
            "audio_bytes": cached[0],
            "media_type": cached[1],
            "model_used": cached[2],
            "task": None,
        }
    else:
        bg_task = asyncio.create_task(_get_or_create_wav_task(cleaned, voice_key, speed, emo_key))
        tts_cache[audio_id] = {
            "text": cleaned,
            "voice": voice_key,
            "speed": speed,
            "engine": engine,
            "emotion": emo_key,
            "created_at": time.time(),
            "audio_bytes": None,
            "media_type": None,
            "model_used": None,
            "task": bg_task,
        }

    return {"status": "ok", "audio_id": audio_id, "url": f"/api/tts/stream/{audio_id}"}


def prestart_tts_background(text: str, voice: str | None = None, engine: str | None = None, emotion: str | None = None) -> None:
    """Intentionally disabled so Gemini TTS tokens are strictly spent on user-triggered playback."""
    return None


@router.post("/pcm-stream")
async def pcm_stream_tts(req: TTSRequest, request: Request):
    """
    Real-time 24kHz 16-bit signed little-endian mono PCM stream (`audio/l16`)
    from Google Gemini 3.8 Flash TTS (`gemini-3.8-flash-tts`) with auth enforcement,
    inflight deduplication, and 0-token LRU caching.
    """
    _require_tts_session(request)
    cleaned = clean_tts_text(req.text)
    if not cleaned:
        raise HTTPException(status_code=400, detail="Empty text after cleaning")
    if len(cleaned) > _MAX_TTS_CHARS:
        cleaned = cleaned[:_MAX_TTS_CHARS]

    voice_key, _ = _resolve_user_tts_prefs(request, req.voice, req.engine)
    speed = max(0.5, min(2.0, float(req.speed or 1.0)))
    emo_key = _infer_emotion_key(req.emotion, cleaned)
    pace = _pace_bucket(speed)
    cache_key = ("pcm", voice_key, emo_key, pace, cleaned)

    cached = _AUDIO_LRU_CACHE.get(cache_key)
    if cached and len(cached[0]) >= 2:
        _AUDIO_LRU_CACHE.move_to_end(cache_key)
        return Response(
            content=cached[0],
            status_code=200,
            media_type="application/octet-stream",
            headers={
                "X-Sample-Rate": "24000",
                "X-TTS-Engine": "gemini",
                "X-TTS-Actual-Model": "cache:" + cached[2],
                "X-TTS-Emotion": emo_key,
                "Cache-Control": "private, max-age=86400",
            },
        )

    inflight = _INFLIGHT_TASKS.get(cache_key)
    if inflight and not inflight.done():
        pcm_bytes, _, model_used = await asyncio.shield(inflight)
        return Response(
            content=pcm_bytes,
            status_code=200,
            media_type="application/octet-stream",
            headers={
                "X-Sample-Rate": "24000",
                "X-TTS-Engine": "gemini",
                "X-TTS-Actual-Model": "cache:" + model_used,
                "X-TTS-Emotion": emo_key,
                "Cache-Control": "private, max-age=86400",
            },
        )

    stream_iter = _stream_gemini_pcm_chunks(cleaned, voice_key, emo_key, speed)
    try:
        first_chunk, actual_model = await stream_iter.__anext__()
    except StopAsyncIteration:
        raise HTTPException(status_code=503, detail="Empty PCM stream from Gemini 3.8 TTS")
    except GeminiTTSUpstreamError as gem_err:
        print(f"[Gemini TTS] {gem_err.error_code} ({gem_err.status_code}): {gem_err.message}")
        raise HTTPException(
            status_code=gem_err.status_code,
            detail={"message": gem_err.message, "code": gem_err.error_code},
        )
    except Exception as e:
        print(f"[Gemini TTS] PCM stream error: {e}")
        raise HTTPException(status_code=503, detail=f"Gemini 3.8 TTS stream unavailable: {e}")

    done_fut: asyncio.Future[tuple[bytes, str, str]] = asyncio.get_running_loop().create_future()
    _INFLIGHT_TASKS[cache_key] = done_fut  # type: ignore[assignment]

    async def _gen():
        collected = bytearray()
        if first_chunk:
            collected.extend(first_chunk)
            yield first_chunk
        completed_cleanly = False
        try:
            async for pcm_chunk, _ in stream_iter:
                collected.extend(pcm_chunk)
                yield pcm_chunk
            completed_cleanly = True
        except Exception as mid_err:
            print(f"[Gemini TTS] Mid-stream interruption: {mid_err}")
        finally:
            if _INFLIGHT_TASKS.get(cache_key) is done_fut:
                _INFLIGHT_TASKS.pop(cache_key, None)
            if completed_cleanly and collected and len(collected) >= 4:
                even_len = len(collected) & ~1
                final_b = bytes(collected[:even_len])
                _store_in_lru(cache_key, final_b, "application/octet-stream", actual_model)
                wav_key = ("wav", voice_key, emo_key, pace, cleaned)
                if wav_key not in _AUDIO_LRU_CACHE:
                    _store_in_lru(wav_key, _wrap_pcm16_as_wav(final_b, 24000), "audio/wav", actual_model)
                if not done_fut.done():
                    done_fut.set_result((final_b, "application/octet-stream", actual_model))
            elif not done_fut.done():
                done_fut.set_exception(RuntimeError("PCM stream interrupted"))

    return StreamingResponse(
        _gen(),
        media_type="application/octet-stream",
        headers={
            "X-Sample-Rate": "24000",
            "X-TTS-Engine": "gemini",
            "X-TTS-Actual-Model": actual_model,
            "X-TTS-Emotion": emo_key,
            "Cache-Control": "private, max-age=86400",
        },
    )


@router.post("")
@router.post("/")
async def direct_tts(req: TTSRequest, request: Request):
    """Single-round-trip synthesis endpoint: returns studio-grade Gemini 3.8 Flash TTS WAV bytes with 24h caching."""
    _require_tts_session(request)
    cleaned = clean_tts_text(req.text)
    if not cleaned:
        raise HTTPException(status_code=400, detail="Empty text after cleaning")
    if len(cleaned) > _MAX_TTS_CHARS:
        cleaned = cleaned[:_MAX_TTS_CHARS]

    voice_key, _ = _resolve_user_tts_prefs(request, req.voice, req.engine)
    speed = max(0.5, min(2.0, float(req.speed or 1.0)))
    emo_key = _infer_emotion_key(req.emotion, cleaned)
    try:
        audio_bytes, media_type, model_used = await _get_or_create_wav_task(cleaned, voice_key, speed, emo_key)
    except GeminiTTSUpstreamError as gem_err:
        print(f"[Gemini TTS] {gem_err.error_code} ({gem_err.status_code}): {gem_err.message}")
        raise HTTPException(
            status_code=gem_err.status_code,
            detail={"message": gem_err.message, "code": gem_err.error_code},
        )
    except Exception as e:
        print(f"[Gemini TTS] Direct synthesis error: {e}")
        raise HTTPException(status_code=503, detail=f"Gemini 3.8 TTS unavailable: {e}")

    return Response(
        content=audio_bytes,
        status_code=200,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(audio_bytes)),
            "Cache-Control": "public, max-age=86400",
            "X-TTS-Engine": "gemini",
            "X-TTS-Actual-Model": model_used,
            "X-TTS-Persona": voice_key,
            "X-TTS-Emotion": emo_key,
        },
    )


@router.api_route("/stream/{audio_id}", methods=["GET", "HEAD"])
async def stream_tts(audio_id: str, request: Request):
    item = tts_cache.get(audio_id)
    if not item:
        raise HTTPException(status_code=404, detail="Audio session expired or not found")

    audio_bytes: bytes | None = item.get("audio_bytes")
    media_type: str | None = item.get("media_type")
    model_used: str = item.get("model_used") or GEMINI_TTS_MODEL

    if audio_bytes is None or media_type is None:
        task: asyncio.Task | None = item.get("task")
        try:
            if task is not None:
                audio_bytes, media_type, model_used = await asyncio.shield(task)
            else:
                audio_bytes, media_type, model_used = await _get_or_create_wav_task(
                    item["text"], item["voice"], item["speed"], item.get("emotion")
                )
            item["audio_bytes"] = audio_bytes
            item["media_type"] = media_type
            item["model_used"] = model_used
        except GeminiTTSUpstreamError as gem_err:
            raise HTTPException(status_code=gem_err.status_code, detail={"message": gem_err.message, "code": gem_err.error_code})
        except Exception as e:
            print(f"[Gemini TTS Stream Error] {e}")
            raise HTTPException(status_code=503, detail="Gemini 3.8 TTS synthesis failed")

    total_len = len(audio_bytes)
    base_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=86400",
        "X-TTS-Engine": "gemini",
        "X-TTS-Actual-Model": model_used,
        "X-TTS-Persona": item.get("voice", "af_bella"),
    }

    if request.method == "HEAD":
        base_headers["Content-Length"] = str(total_len)
        return Response(content=b"", status_code=200, media_type=media_type, headers=base_headers)

    range_header = request.headers.get("range") or request.headers.get("Range")
    if range_header and range_header.strip().lower().startswith("bytes="):
        try:
            range_spec = range_header.strip()[6:].split(",")[0].strip()
            start_str, end_str = range_spec.split("-", 1)
            if start_str == "":
                suffix_len = int(end_str)
                start = max(0, total_len - suffix_len)
                end = total_len - 1
            else:
                start = int(start_str)
                end = int(end_str) if end_str else total_len - 1
            start = max(0, min(start, total_len - 1))
            end = max(start, min(end, total_len - 1))
            chunk = audio_bytes[start : end + 1]
            headers = {
                **base_headers,
                "Content-Range": f"bytes {start}-{end}/{total_len}",
                "Content-Length": str(len(chunk)),
            }
            return Response(content=chunk, status_code=206, media_type=media_type, headers=headers)
        except Exception:
            pass

    base_headers["Content-Length"] = str(total_len)
    return Response(content=audio_bytes, status_code=200, media_type=media_type, headers=base_headers)


@router.get("/personas")
async def list_tts_personas():
    return {
        "engine": "gemini",
        "model": GEMINI_TTS_MODEL,
        "fallback_model": GEMINI_TTS_FALLBACK_MODEL,
        "gemini_configured": bool(_get_gemini_api_key()),
        "personas": [
            {
                "id": p["id"],
                "short_id": p["short_id"],
                "name": p["name"],
                "role": p["role"],
                "gemini_voice": p["gemini_voice"],
            }
            for p in PERSONA_CONFIG.values()
        ],
    }


def init_gemini_tts() -> None:
    """Log Gemini 3.8 Flash TTS readiness without pre-warming on startup (saves credits until user triggers audio)."""
    if _get_gemini_api_key():
        print(
            f"[Gemini TTS] Ready ({GEMINI_TTS_MODEL}, fallback={GEMINI_TTS_FALLBACK_MODEL}) — "
            "Bella=Aoede, Sarah=Leda, Adam=Puck, Michael=Achird (on-demand synthesis only; startup pre-warm disabled)."
        )
    else:
        print("[Gemini TTS] Warning: GEMINI_API_KEY not configured.")


def init_openai_tts() -> None:
    init_gemini_tts()


def init_kokoro(*args, **kwargs) -> None:
    init_gemini_tts()
