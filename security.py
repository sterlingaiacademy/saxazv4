import secrets
from datetime import datetime, timedelta, timezone
import bcrypt
from fastapi import Request, Response, HTTPException, status
from typing import Optional

def verify_password(plain_password, hashed_password):
    try:
        if isinstance(plain_password, str):
            plain_password = plain_password.encode('utf-8')
        plain_password = plain_password[:72]
        if isinstance(hashed_password, str):
            hashed_password = hashed_password.encode('utf-8')
        return bcrypt.checkpw(plain_password, hashed_password)
    except (ValueError, TypeError):
        return False

def get_password_hash(password):
    if isinstance(password, str):
        password = password.encode('utf-8')
    password = password[:72]
    return bcrypt.hashpw(password, bcrypt.gensalt()).decode('utf-8')


# ---------------------------------------------------------------------------
# Stateless signed tokens (used on Vercel, where every serverless instance has
# its own /tmp database so DB-backed sessions cannot be shared between them).
# Enabled only when running on Vercel AND SESSION_SECRET is configured.
# ---------------------------------------------------------------------------
import os as _os
import hmac as _hmac
import hashlib as _hashlib
import time as _time
import json as _json
import base64 as _b64
import zlib as _zlib
import urllib.request as _urlreq
import urllib.error as _urlerr

_LAST_BLOB_SYNC_TS: float = 0.0
_BLOB_SYNC_TTL: float = 10.0

def _blob_token() -> str:
    return (_os.environ.get("BLOB_READ_WRITE_TOKEN") or "").strip().strip('"')

def _blob_public_base(token: str) -> Optional[str]:
    parts = token.split("_")
    if len(parts) >= 4 and parts[3]:
        return f"https://{parts[3].lower()}.public.blob.vercel-storage.com"
    return None

def _user_blob_key(email: str) -> str:
    clean = (email or "").strip().lower()
    h = _hashlib.sha256(clean.encode("utf-8")).hexdigest()[:24]
    return f"saxaz_user_{h}.json"

def _put_blob_json(pathname: str, data_obj: dict) -> bool:
    token = _blob_token()
    if not token:
        return False
    try:
        payload = _json.dumps(data_obj).encode("utf-8")
        req = _urlreq.Request(
            f"https://vercel.com/api/blob/?pathname={pathname}",
            data=payload,
            headers={
                "authorization": f"Bearer {token}",
                "x-api-version": "12",
                "x-content-type": "application/json",
                "x-vercel-blob-access": "public",
                "x-add-random-suffix": "0",
                "x-allow-overwrite": "1",
                "x-cache-control-max-age": "0",
            },
            method="PUT",
        )
        with _urlreq.urlopen(req, timeout=8) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        print(f"Blob PUT error ({pathname}): {e}")
        return False

def _get_blob_json(pathname: str) -> Optional[dict]:
    token = _blob_token()
    if not token:
        return None
    base = _blob_public_base(token)
    if not base:
        return None
    try:
        url = f"{base}/{pathname}?t={_time.time()}"
        req = _urlreq.Request(url, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
        with _urlreq.urlopen(req, timeout=6) as resp:
            return _json.loads(resp.read().decode("utf-8"))
    except _urlerr.HTTPError as e:
        if e.code != 404:
            print(f"Blob GET HTTP error ({pathname}): {e.code}")
        return None
    except Exception as e:
        print(f"Blob GET error ({pathname}): {e}")
        return None

def sync_users_from_blob(conn, force: bool = False, target_email: Optional[str] = None) -> None:
    global _LAST_BLOB_SYNC_TS
    token = _blob_token()
    if not token:
        return
    now = _time.time()
    # 1. If a specific target_email is requested (e.g. during login/register), check its dedicated per-user blob first
    if target_email:
        u_data = _get_blob_json(_user_blob_key(target_email))
        if isinstance(u_data, dict) and u_data.get("email"):
            ensure_user_row(conn, u_data)

    # 2. Sync the shared users index blob (with short TTL unless forced)
    if not force and (now - _LAST_BLOB_SYNC_TS) < _BLOB_SYNC_TTL:
        return
    _LAST_BLOB_SYNC_TS = now
    blob_data = _get_blob_json("saxaz_users_v1.json")
    if isinstance(blob_data, dict):
        users_map = blob_data.get("users")
        if isinstance(users_map, dict):
            for _, u_rec in users_map.items():
                if isinstance(u_rec, dict) and u_rec.get("email"):
                    ensure_user_row(conn, u_rec)

def save_user_to_blob(conn, user_record: dict) -> None:
    token = _blob_token()
    if not token or not user_record or not user_record.get("email"):
        return
    email_key = str(user_record["email"]).strip().lower()
    # 1. Write dedicated per-user blob immediately (zero CDN cache or race collision)
    _put_blob_json(_user_blob_key(email_key), user_record)

    # 2. Merge with existing saxaz_users_v1.json and local DB users and update master index
    merged_users: dict[str, dict] = {}
    existing_blob = _get_blob_json("saxaz_users_v1.json")
    if isinstance(existing_blob, dict) and isinstance(existing_blob.get("users"), dict):
        for k, v in existing_blob["users"].items():
            if isinstance(v, dict) and v.get("email"):
                merged_users[str(v["email"]).strip().lower()] = v
    try:
        rows = conn.execute("SELECT id, name, email, password_hash, role, class_id FROM users").fetchall()
        for r in rows:
            d = dict(r)
            if d.get("email"):
                merged_users[str(d["email"]).strip().lower()] = d
    except Exception:
        pass
    merged_users[email_key] = user_record
    _put_blob_json("saxaz_users_v1.json", {"users": merged_users, "updated_at": _time.time()})

def _secret() -> bytes:
    return (_os.environ.get("SESSION_SECRET") or "saxaz-v3-default-hmac-secret-2026").encode("utf-8")

def stateless_enabled() -> bool:
    return True

def _sign(payload: str) -> str:
    return _hmac.new(_secret(), payload.encode("utf-8"), _hashlib.sha256).hexdigest()

def deterministic_user_id(email: str) -> int:
    clean = (email or "").strip().lower()
    return 10000 + (_zlib.crc32(clean.encode("utf-8")) % 900000)

def encode_signed_json(kind: str, obj) -> str:
    raw = _json.dumps(obj, separators=(",", ":")).encode("utf-8")
    b64 = _b64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    payload = f"{kind}.{b64}"
    return f"{payload}.{_sign(payload)}"

def decode_signed_json(token: str, kind: str):
    try:
        if not token:
            return None
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != kind:
            return None
        payload = f"{parts[0]}.{parts[1]}"
        if not _hmac.compare_digest(_sign(payload), parts[2]):
            return None
        pad = "=" * ((4 - len(parts[1]) % 4) % 4)
        raw = _b64.urlsafe_b64decode((parts[1] + pad).encode("ascii"))
        return _json.loads(raw.decode("utf-8"))
    except Exception:
        return None

def ensure_user_row(conn, u: dict) -> Optional[dict]:
    if not u or not u.get("email") or not u.get("password_hash"):
        return None
    email = str(u["email"]).strip()
    uid = int(u.get("id") or deterministic_user_id(email))
    name = str(u.get("name") or email.split("@")[0]).strip()
    pw_hash = str(u["password_hash"])
    role = str(u.get("role") or "student")
    class_id = int(u.get("class_id") or 1)

    row = conn.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?) OR id = ?", (email, uid)).fetchone()
    if row:
        return dict(row)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO users (
                id, name, email, password_hash, role, class_id,
                tts_engine, tts_mode, sfx_mode, sfx_enabled,
                cursor_mode, cursor_effect, subject_intro_mode
            ) VALUES (?, ?, ?, ?, ?, ?, 'kokoro', 'auto', 0, 0, 1, 'none', 0)
            """,
            (uid, name, email, pw_hash, role, class_id)
        )
        conn.commit()
    except Exception:
        pass
    row = conn.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?) OR id = ?", (email, uid)).fetchone()
    return dict(row) if row else None

def hydrate_vault_cookie(request: Request, conn, extra_vault_token: Optional[str] = None) -> list[dict]:
    sync_users_from_blob(conn)
    accounts: list[dict] = []
    seen_emails = set()
    for tok in (request.cookies.get("saxaz_vault"), extra_vault_token):
        if not tok:
            continue
        items = decode_signed_json(tok, "v1")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("email"):
                    em = str(item["email"]).strip().lower()
                    if em not in seen_emails:
                        seen_emails.add(em)
                        accounts.append(item)
                    ensure_user_row(conn, item)
    return accounts

def make_signed_token(kind: str, uid: int, flag: int, ttl_seconds: int) -> str:
    payload = f"{kind}.{int(uid)}.{int(flag)}.{int(_time.time()) + int(ttl_seconds)}"
    return f"{payload}.{_sign(payload)}"

def read_signed_token(token: str, kind: str):
    """Return (uid, flag) when the token is authentic and unexpired, else None."""
    try:
        if not token:
            return None
        parts = token.split(".")
        if len(parts) != 5 or parts[0] != kind:
            return None
        payload = ".".join(parts[:4])
        if not _hmac.compare_digest(_sign(payload), parts[4]):
            return None
        if int(parts[3]) < _time.time():
            return None
        return int(parts[1]), int(parts[2])
    except Exception:
        return None

def create_session(conn, user_id: int, expires_days: int = 7, is_parent: int = 0) -> str:
    row = conn.execute("SELECT id, name, email, password_hash, role, class_id FROM users WHERE id = ?", (user_id,)).fetchone()
    if row:
        return encode_signed_json("s2", {
            "u": int(row["id"]),
            "p": int(is_parent),
            "exp": int(_time.time()) + int(expires_days * 86400),
            "n": row["name"],
            "e": row["email"],
            "h": row["password_hash"],
            "r": row["role"],
            "c": row["class_id"] or 1,
        })
    return make_signed_token("s", user_id, is_parent, expires_days * 24 * 60 * 60)

def _apply_prefs_cookie(request: Request, conn, user: dict) -> dict:
    """Overlay signed saxaz_prefs cookie and hydrate student coin wallet so state persists across Vercel Serverless instances."""
    if not user:
        return user
    try:
        if user.get("role") == "student":
            import services.reward_service as _reward_svc
            _reward_svc.hydrate_student_wallet(request, conn, user)
    except Exception:
        pass
    if user.get("is_parent"):
        return user
    raw = request.cookies.get("saxaz_prefs")
    if not raw:
        return user
    prefs = decode_signed_json(raw, "p1")
    if not isinstance(prefs, dict) or int(prefs.get("uid") or -1) != int(user.get("id") or -2):
        return user
    pref_keys = (
        "tts_voice",
        "tts_engine",
        "tts_mode",
        "tutor_lang",
        "sfx_mode",
        "sfx_custom",
        "cursor_mode",
        "cursor_effect",
        "subject_intro_mode",
        "game_prompt_mode",
    )
    changed = False
    for k in pref_keys:
        if k in prefs and prefs[k] is not None and user.get(k) != prefs[k]:
            user[k] = prefs[k]
            changed = True
    if changed:
        try:
            conn.execute(
                """
                UPDATE users
                SET tts_voice = ?, tts_engine = ?, tts_mode = ?, tutor_lang = ?,
                    sfx_mode = ?, sfx_custom = ?, cursor_mode = ?, cursor_effect = ?, subject_intro_mode = ?,
                    game_prompt_mode = ?
                WHERE id = ?
                """,
                (
                    user.get("tts_voice") or "af_bella",
                    user.get("tts_engine") or "openai",
                    user.get("tts_mode") or "auto",
                    user.get("tutor_lang") or "en",
                    int(user.get("sfx_mode") or 0),
                    user.get("sfx_custom") or "{}",
                    int(user.get("cursor_mode") if user.get("cursor_mode") is not None else 1),
                    user.get("cursor_effect") or "none",
                    int(user.get("subject_intro_mode") or 0),
                    (user.get("game_prompt_mode") or "always"),
                    user["id"],
                ),
            )
            conn.commit()
        except Exception:
            pass
    return user


def set_prefs_cookie(response: Response, uid: int, prefs: dict) -> str:
    is_production = _os.environ.get("K_SERVICE") is not None or bool(_os.environ.get("VERCEL"))
    payload = {"uid": int(uid), **(prefs or {})}
    tok = encode_signed_json("p1", payload)
    response.set_cookie(
        key="saxaz_prefs",
        value=tok,
        httponly=False,
        max_age=365 * 24 * 60 * 60,
        samesite="lax",
        secure=is_production,
    )
    return tok


def get_current_user(request: Request, conn):
    session_id = request.cookies.get("session_id") or request.cookies.get("__session")
    if not session_id:
        return None

    # Self-healing stateless signed session v2 (embeds user profile for cold serverless instances)
    if session_id.startswith("s2."):
        data = decode_signed_json(session_id, "s2")
        if not data or int(data.get("exp", 0)) < _time.time():
            return None
        uid = int(data["u"])
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if not row and data.get("e") and data.get("h"):
            hydrate_vault_cookie(request, conn)
            ensure_user_row(conn, {
                "id": uid,
                "name": data.get("n"),
                "email": data.get("e"),
                "password_hash": data.get("h"),
                "role": data.get("r") or "student",
                "class_id": data.get("c") or 1,
            })
            row = conn.execute("SELECT * FROM users WHERE id = ? OR email = ?", (uid, data.get("e"))).fetchone()
        if not row:
            return None
        user = dict(row)
        user["is_parent"] = int(data.get("p", 0))
        return _apply_prefs_cookie(request, conn, user)

    hydrate_vault_cookie(request, conn)

    # Stateless signed session v1
    if session_id.startswith("s."):
        data = read_signed_token(session_id, "s")
        if not data:
            return None
        row = conn.execute("SELECT * FROM users WHERE id = ?", (data[0],)).fetchone()
        if not row:
            return None
        user = dict(row)
        user["is_parent"] = data[1]
        return _apply_prefs_cookie(request, conn, user)

    # Check DB session fallback
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.*, s.is_parent FROM users u
        JOIN sessions s ON u.id = s.user_id
        WHERE s.id = ? AND s.expires_at > ?
    """, (session_id, datetime.now(timezone.utc).isoformat()))
    
    user = cursor.fetchone()
    if not user:
        return None
    
    return _apply_prefs_cookie(request, conn, dict(user))

def require_admin(request: Request, conn):
    user = get_current_user(request, conn)
    if not user or user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"}
        )
    return user

def require_student(request: Request, conn):
    user = get_current_user(request, conn)
    if not user or user["role"] != "student" or user.get("is_parent"):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"}
        )
    return user

def require_parent(request: Request, conn):
    user = get_current_user(request, conn)
    if not user or user["role"] != "student" or not user.get("is_parent"):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"}
        )
    return user

def require_auth(request: Request, conn):
    user = get_current_user(request, conn)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"}
        )
    return user

def set_auth_cookie(response: Response, session_id: str, expires_days: int = 7):
    import os
    is_production = os.environ.get("K_SERVICE") is not None or bool(os.environ.get("VERCEL"))  # Cloud Run / Vercel (HTTPS)
    # Set both `session_id` and `__session` (Firebase Hosting forwards only `__session` to Cloud Run)
    for cookie_name in ("session_id", "__session"):
        response.set_cookie(
            key=cookie_name,
            value=session_id,
            httponly=True,
            max_age=expires_days * 24 * 60 * 60,
            samesite="lax",
            secure=is_production,
            path="/",
        )

def set_vault_cookie(response: Response, accounts: list[dict]):
    import os
    is_production = os.environ.get("K_SERVICE") is not None or bool(os.environ.get("VERCEL"))
    trimmed = accounts[-8:] if len(accounts) > 8 else accounts
    tok = encode_signed_json("v1", trimmed)
    response.set_cookie(
        key="saxaz_vault",
        value=tok,
        httponly=False,
        max_age=365 * 24 * 60 * 60,
        samesite="lax",
        secure=is_production
    )
    return tok

def remove_auth_cookie(response: Response):
    response.delete_cookie("session_id", path="/")
    response.delete_cookie("__session", path="/")
