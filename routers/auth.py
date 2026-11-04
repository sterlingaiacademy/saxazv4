from fastapi import APIRouter, Request, Form, Depends, HTTPException, status, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import sqlite3
from typing import Optional

from database import get_db_connection
from security import get_password_hash, verify_password, create_session, remove_auth_cookie, set_auth_cookie

router = APIRouter()
templates = Jinja2Templates(directory="templates")

import time as _time
import secrets as _secrets

# Short-lived pre-auth tokens for parent PIN verification: token -> (uid, expires_ts)
_PARENT_PREAUTH_TOKENS: dict[str, tuple[int, float]] = {}
# Brute-force protection for parent PIN: uid -> [failed_count, lockout_until_ts]
_PARENT_PIN_ATTEMPTS: dict[int, list[float]] = {}

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
  return templates.TemplateResponse(request=request, name="auth/login.html", context={"request": request})

@router.post("/login")
async def login(
  request: Request,
  response: Response,
  email: str = Form(...),
  password: str = Form(...)
):
  conn = get_db_connection()
  try:
    is_parent = False
    if email.startswith("p-"):
      is_parent = True
      email = email[2:]

    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    
    if not user or not verify_password(password[:72], user["password_hash"]):
      return templates.TemplateResponse(request=request, name=
        "auth/login.html", 
        context={"request": request, "error": "Invalid email or password"}
      )
      
    if is_parent:
      if user["parent_locked"] == 1:
        # Issue a short-lived (10 min) pre-auth token so PIN endpoint cannot be accessed without password
        import os as _os
        now_ts = _time.time()
        preauth_token = _secrets.token_urlsafe(24)
        if len(_PARENT_PREAUTH_TOKENS) > 500:
          expired_keys = [k for k, v in _PARENT_PREAUTH_TOKENS.items() if v[1] < now_ts]
          for k in expired_keys:
            _PARENT_PREAUTH_TOKENS.pop(k, None)
        _PARENT_PREAUTH_TOKENS[preauth_token] = (user["id"], now_ts + 600)
        redirect = RedirectResponse(url=f"/login/parent-pin?uid={user['id']}", status_code=status.HTTP_302_FOUND)
        redirect.set_cookie(
          key="parent_preauth",
          value=preauth_token,
          httponly=True,
          max_age=600,
          samesite="lax",
          secure=_os.environ.get("K_SERVICE") is not None
        )
        return redirect
      else:
        session_id = create_session(conn, user["id"], is_parent=1)
        redirect_url = "/parent/dashboard"
    else:
      session_id = create_session(conn, user["id"], is_parent=0)
      redirect_url = "/admin/dashboard" if user["role"] == "admin" else "/student/dashboard"
      
    redirect = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    set_auth_cookie(redirect, session_id)
    
    return redirect
  finally:
    conn.close()

@router.get("/login/parent-pin", response_class=HTMLResponse)
async def parent_pin_page(request: Request, uid: int):
  preauth = request.cookies.get("parent_preauth")
  token_data = _PARENT_PREAUTH_TOKENS.get(preauth or "")
  if not token_data or token_data[0] != uid or token_data[1] < _time.time():
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
  return templates.TemplateResponse(request=request, name="auth/parent_pin.html", context={"request": request, "uid": uid})

@router.post("/login/parent-pin")
async def parent_pin_submit(request: Request, uid: int = Form(...), pin: str = Form(...)):
  now = _time.time()
  preauth = request.cookies.get("parent_preauth")
  token_data = _PARENT_PREAUTH_TOKENS.get(preauth or "")
  if not token_data or token_data[0] != uid or token_data[1] < now:
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

  attempt_info = _PARENT_PIN_ATTEMPTS.get(uid, [0, 0.0])
  if attempt_info[1] > now:
    wait_secs = int(attempt_info[1] - now)
    return templates.TemplateResponse(
      request=request,
      name="auth/parent_pin.html",
      context={"request": request, "uid": uid, "error": f"Too many failed attempts. Please wait {wait_secs}s."}
    )

  conn = get_db_connection()
  try:
    cursor = conn.cursor()
    cursor.execute("SELECT id, parent_pin FROM users WHERE id = ?", (uid,))
    user = cursor.fetchone()
    
    if not user or not _secrets.compare_digest(str(user["parent_pin"] or ""), str(pin or "")):
      fails = int(attempt_info[0]) + 1
      lockout_until = (now + 300) if fails >= 5 else 0.0
      _PARENT_PIN_ATTEMPTS[uid] = [0 if fails >= 5 else fails, lockout_until]
      return templates.TemplateResponse(request=request, name=
        "auth/parent_pin.html", 
        context={"request": request, "uid": uid, "error": "Invalid PIN"}
      )
      
    _PARENT_PIN_ATTEMPTS.pop(uid, None)
    _PARENT_PREAUTH_TOKENS.pop(preauth or "", None)
    session_id = create_session(conn, user["id"], is_parent=1)
    redirect = RedirectResponse(url="/parent/dashboard", status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie("parent_preauth")
    set_auth_cookie(redirect, session_id)
    return redirect
  finally:
    conn.close()

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
  conn = get_db_connection()
  try:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM classes ORDER BY order_index, id")
    classes = [dict(row) for row in cursor.fetchall()]
    return templates.TemplateResponse(request=request, name="auth/register.html", context={"request": request, "classes": classes})
  finally:
    conn.close()

@router.post("/register")
async def register(
  request: Request,
  name: str = Form(...),
  email: str = Form(...),
  password: str = Form(...),
  class_id: int = Form(...)
):
  conn = get_db_connection()
  try:
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    if cursor.fetchone():
      cursor.execute("SELECT * FROM classes ORDER BY order_index, id")
      classes = [dict(row) for row in cursor.fetchall()]
      return templates.TemplateResponse(request=request, name=
        "auth/register.html", 
        context={"request": request, "error": "Email already registered.", "classes": classes}
      )
      
    hashed_pw = get_password_hash(password[:72])
    cursor.execute(
      """
      INSERT INTO users (
        name, email, password_hash, role, class_id,
        tts_engine, tts_mode, sfx_mode, sfx_enabled,
        cursor_mode, cursor_effect, subject_intro_mode
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      """,
      (
        name, email, hashed_pw, 'student', class_id,
        'kokoro', 'auto', 0, 0,
        1, 'none', 0
      )
    )
    user_id = cursor.lastrowid
    conn.commit()
    
    # Auto-login after registration
    session_id = create_session(conn, user_id)
    
    redirect = RedirectResponse(url="/student/dashboard", status_code=status.HTTP_302_FOUND)
    set_auth_cookie(redirect, session_id)
    
    return redirect
  except Exception as e:
    conn.rollback()
    print(f"Registration error: {e}")
    classes = []
    try:
      cursor = conn.cursor()
      cursor.execute("SELECT * FROM classes ORDER BY order_index, id")
      classes = [dict(row) for row in cursor.fetchall()]
    except Exception:
      pass
    return templates.TemplateResponse(request=request, name=
      "auth/register.html", 
      context={"request": request, "error": "Unable to complete registration. Please check your details and try again.", "classes": classes}
    )
  finally:
    conn.close()

@router.get("/logout")
async def logout(request: Request, response: Response):
  conn = get_db_connection()
  session_id = request.cookies.get("session_id")
  if session_id:
    try:
      conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
      conn.commit()
    except Exception as e:
      print(f"Logout session delete error: {e}")
    finally:
      conn.close()
  else:
    conn.close()
      
  redirect = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
  remove_auth_cookie(redirect)
  return redirect

@router.post("/set-theme")
async def set_theme(request: Request, theme: str = Form(...)):
  # Optional endpoint if we want to save theme to the db user record
  session_id = request.cookies.get("session_id")
  if session_id and theme in ('light', 'dark'):
    conn = get_db_connection()
    try:
      conn.execute("""
        UPDATE users SET theme_preference = ? 
        WHERE id = (SELECT user_id FROM sessions WHERE id = ?)
      """, (theme, session_id))
      conn.commit()
    except Exception as e:
      print(f"Theme save error: {e}")
    finally:
      conn.close()
  return Response(status_code=status.HTTP_200_OK)
