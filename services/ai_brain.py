"""The AI brain: Gemini for everything (tutor, marking, Why?, parent notes, search, microphone).
The voice is Gemini too (routers/tts.py). One Google key (GEMINI_API_KEY) runs the whole site.

Gemini offers an OpenAI-compatible endpoint, so a Gemini reply has exactly the shape the existing
code reads (`resp.choices[0].message.content`, streamed chunks, JSON mode). Thinking is switched off
("none") so no hidden extra tokens are spent and replies come back fast.
"""
from __future__ import annotations

import base64
import os

import httpx
from openai import OpenAI  # only the client library; requests go to Google's Gemini endpoint

GEMINI_TEXT_MODEL = (os.getenv("GEMINI_TEXT_MODEL") or "gemini-3.8-flash").strip()
_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_client: OpenAI | None = None


def _key() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip().strip('"')


def available() -> bool:
    return bool(_key())


def _gemini() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=_key(), base_url=_BASE_URL, timeout=25.0, max_retries=1)
    return _client


def _has_image(messages: list) -> bool:
    for m in messages or []:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in content):
            return True
    return False


def chat(messages: list, stream: bool = False, temperature: float = 0.5, max_tokens: int = 220, json_mode: bool = False,
         timeout: float | None = None):
    """Same call shape and return value as an OpenAI `chat.completions.create` call."""
    if not available():
        raise RuntimeError("GEMINI_API_KEY is not configured")
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    cl = _gemini().with_options(timeout=timeout) if timeout else _gemini()
    # Pictures (scratchpad drawings, photos) make Gemini spend some hidden tokens reading them even with
    # thinking off, so give those calls extra room; the cap is a limit, not what gets spent.
    if _has_image(messages):
        max_tokens += 512
    try:
        resp = cl.chat.completions.create(
            model=GEMINI_TEXT_MODEL, messages=messages, stream=stream, temperature=temperature,
            max_tokens=max_tokens, reasoning_effort="none", **kwargs,
        )
        if not stream and resp.choices and not (resp.choices[0].message.content or "").strip() \
                and resp.choices[0].finish_reason == "length":
            # ran out of room before writing anything: one retry with more room
            resp = cl.chat.completions.create(
                model=GEMINI_TEXT_MODEL, messages=messages, stream=stream, temperature=temperature,
                max_tokens=max_tokens + 1024, reasoning_effort="none", **kwargs,
            )
        return resp
    except Exception as e:
        # a model that cannot switch thinking off: retry with the lowest level it accepts
        if "thinking" in str(e).lower() or "reasoning" in str(e).lower():
            return cl.chat.completions.create(
                model=GEMINI_TEXT_MODEL, messages=messages, stream=stream, temperature=temperature,
                max_tokens=max_tokens + 400, reasoning_effort="low", **kwargs,
            )
        raise


def transcribe(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    """Speech to text (the student's microphone). Returns "" when nothing clear was said or on any problem."""
    if not available() or not audio_bytes:
        return ""
    clean_mime = (mime_type or "audio/webm").split(";")[0].strip() or "audio/webm"
    body = {
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": clean_mime, "data": base64.b64encode(audio_bytes).decode("ascii")}},
            {"text": "Transcribe exactly what the student says, in the language they speak. "
                     "Return only the words, nothing else. If there is no clear speech, return nothing."},
        ]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 300, "thinkingConfig": {"thinkingBudget": 0}},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_TEXT_MODEL}:generateContent"
    headers = {"x-goog-api-key": _key()}
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=25.0)
        if r.status_code >= 400 and "thinking" in r.text.lower():
            body["generationConfig"].pop("thinkingConfig", None)
            body["generationConfig"]["maxOutputTokens"] = 800
            r = httpx.post(url, json=body, headers=headers, timeout=25.0)
        if r.status_code >= 400:
            print(f"Gemini transcription HTTP {r.status_code}: {r.text[:160]}")
            return ""
        parts = (((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
        return " ".join(str(p.get("text") or "") for p in parts).strip()
    except Exception as e:
        print(f"Gemini transcription error: {e}")
        return ""
