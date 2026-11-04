import os
import re
import hmac
import json
import time
import base64
import hashlib
import secrets

# Persistent server-side secret for signing video vault tokens
_VAULT_SECRET = (os.environ.get("VIDEO_VAULT_SECRET") or os.environ.get("OPENAI_API_KEY") or "saxaz-ultra-vault-key-2026").encode("utf-8")

_YT_REGEX = re.compile(r'(?:youtu\.be/|youtube\.com/(?:embed/|v/|watch\?v=|shorts/|.*[?&]v=))([A-Za-z0-9_-]{11})')


def extract_youtube_id(url: str) -> str | None:
    """Extract the 11-character YouTube video ID from any YouTube URL or raw 11-char ID."""
    if not url or not isinstance(url, str):
        return None
    cleaned = url.strip()
    if re.match(r'^[A-Za-z0-9_-]{11}$', cleaned):
        return cleaned
    match = _YT_REGEX.search(cleaned)
    if match:
        return match.group(1)
    return None


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def create_vault_token(url_or_id: str) -> str:
    """
    Converts any YouTube URL or ID into an opaque, encrypted, HMAC-signed vault token (vtok_...).
    If the input is not a YouTube URL/ID (e.g. a local /media/... MP4), returns it unchanged.
    """
    if not url_or_id or not isinstance(url_or_id, str):
        return ""
    if url_or_id.startswith("vtok_"):
        return url_or_id
    yt_id = extract_youtube_id(url_or_id)
    if not yt_id:
        return url_or_id

    # Encrypt the 11-char ID with an 8-byte random salt derived key + HMAC signature
    salt = secrets.token_bytes(6)
    stream_key = hashlib.sha256(_VAULT_SECRET + salt).digest()
    cipher = _xor_bytes(yt_id.encode("utf-8"), stream_key)
    mac = hmac.new(_VAULT_SECRET, salt + cipher, hashlib.sha256).digest()[:10]
    raw = salt + cipher + mac
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"vtok_{encoded}"


def resolve_vault_token(token: str) -> str | None:
    """
    Verifies and decrypts a vtok_... token back into the 11-character YouTube ID.
    Also accepts raw YouTube URLs as a safe fallback for backward compatibility.
    """
    if not token or not isinstance(token, str):
        return None
    cleaned = token.strip()
    if not cleaned.startswith("vtok_"):
        return extract_youtube_id(cleaned)

    b64 = cleaned[5:]
    padding = "=" * ((4 - len(b64) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(b64 + padding)
        if len(raw) < 27:  # 6 salt + 11 cipher + 10 mac
            return None
        salt = raw[:6]
        cipher = raw[6:-10]
        mac = raw[-10:]
        expected_mac = hmac.new(_VAULT_SECRET, salt + cipher, hashlib.sha256).digest()[:10]
        if not hmac.compare_digest(mac, expected_mac):
            return None
        stream_key = hashlib.sha256(_VAULT_SECRET + salt).digest()
        yt_id = _xor_bytes(cipher, stream_key).decode("utf-8")
        if re.match(r'^[A-Za-z0-9_-]{11}$', yt_id):
            return yt_id
    except Exception:
        return None
    return None


def encode_client_payload(yt_id: str) -> dict:
    """
    Obfuscates the resolved ID with a per-response one-time pad so network responses
    never contain a plain 'youtube.com' URL or readable video ID string.
    """
    nonce = secrets.token_hex(8)
    key_bytes = nonce.encode("ascii")
    masked = [b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(yt_id.encode("utf-8"))]
    return {"k": nonce, "d": masked}


def tokenize_additional_videos(additional_videos_raw):
    """
    Takes either a JSON string or list of additional_videos dicts and replaces any YouTube URLs
    with opaque vtok_... tokens.
    """
    if not additional_videos_raw:
        return []
    is_str = isinstance(additional_videos_raw, str)
    try:
        items = json.loads(additional_videos_raw) if is_str else list(additional_videos_raw)
    except Exception:
        return [] if not is_str else "[]"

    out = []
    for item in items:
        if isinstance(item, dict):
            item_copy = dict(item)
            url = item_copy.get("url") or ""
            if item_copy.get("type") == "youtube" or extract_youtube_id(url):
                item_copy["url"] = create_vault_token(url)
                item_copy["type"] = "youtube"
            out.append(item_copy)
    return json.dumps(out) if is_str else out
