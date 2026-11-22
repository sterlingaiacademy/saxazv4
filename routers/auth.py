import os as _os
import secrets as _secrets
import time as _time
from typing import Optional

from fastapi import APIRouter, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import get_db_connection
import security
from security import (
    create_session,
    deterministic_user_id,
    ensure_user_row,
    get_password_hash,
    hydrate_vault_cookie,
    make_signed_token,
    read_signed_token,
    remove_auth_cookie,
    save_user_to_blob,
    set_auth_cookie,
    set_vault_cookie,
    stateless_enabled,
    sync_users_from_blob,
    verify_password,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Short-lived pre-auth tokens for parent PIN verification: token -> (uid, expires_ts)
_PARENT_PREAUTH_TOKENS: dict[str, tuple[int, float]] = {}
# Brute-force protection for parent PIN: uid -> [failed_count, lockout_until_ts]
_PARENT_PIN_ATTEMPTS: dict[int, list[float]] = {}


def _is_secure_cookie() -> bool:
    return bool(_os.environ.get("K_SERVICE") or _os.environ.get("VERCEL"))


def _issue_parent_preauth_redirect(uid: int, preserve_session: bool = False) -> RedirectResponse:
    now_ts = _time.time()
    preauth_token = (
        make_signed_token("p", uid, 0, 600)
        if stateless_enabled()
        else _secrets.token_urlsafe(24)
    )
    if len(_PARENT_PREAUTH_TOKENS) > 500:
        expired_keys = [k for k, v in _PARENT_PREAUTH_TOKENS.items() if v[1] < now_ts]
        for k in expired_keys:
            _PARENT_PREAUTH_TOKENS.pop(k, None)
    _PARENT_PREAUTH_TOKENS[preauth_token] = (uid, now_ts + 600)
    redirect = RedirectResponse(
        url=f"/login/parent-pin?uid={uid}",
        status_code=status.HTTP_302_FOUND,
    )
    secure_flag = bool(_os.environ.get("K_SERVICE") or _os.environ.get("VERCEL"))
    redirect.set_cookie(
        key="parent_preauth",
        value=preauth_token,
        httponly=True,
        max_age=600,
        samesite="lax",
        secure=secure_flag,
        path="/",
    )
    if not preserve_session:
        redirect.set_cookie(
            key="__session",
            value=preauth_token,
            httponly=True,
            max_age=600,
            samesite="lax",
            secure=secure_flag,
            path="/",
        )
    return redirect


def _preauth_valid(token: Optional[str], uid: int) -> bool:
    """True when the parent pre-auth cookie is valid for this uid (signed on Vercel, in-memory elsewhere)."""
    if token and token.startswith("p."):
        data = read_signed_token(token, "p")
        return bool(data and data[0] == uid)
    token_data = _PARENT_PREAUTH_TOKENS.get(token or "")
    return bool(token_data and token_data[0] == uid and token_data[1] >= _time.time())


def _fetch_classes(conn) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM classes ORDER BY id ASC")
    return [dict(row) for row in cursor.fetchall()]


def _default_class_id(classes: list[dict], requested_id: Optional[int] = None) -> int:
    valid_ids = {int(c["id"]) for c in classes if c.get("id") is not None}
    if requested_id is not None and int(requested_id) in valid_ids:
        return int(requested_id)
    for c in classes:
        cname = str(c.get("name") or "")
        if "10" in cname or int(c["id"]) == 10:
            return int(c["id"])
    if classes:
        return int(classes[0]["id"])
    return 10


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, role: Optional[str] = None):
    portal_role = "parent" if (role or "").strip().lower() == "parent" else "student"
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"request": request, "portal_role": portal_role},
    )


@router.get("/demo-login")
async def demo_login(request: Request):
    if _os.environ.get("SAXAZ_ALLOW_DEMO") != "1":
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE LOWER(email) = 'nimesh@gmail.com' OR role = 'student' "
            "ORDER BY CASE WHEN LOWER(email) = 'nimesh@gmail.com' THEN 0 ELSE 1 END, id ASC LIMIT 1"
        )
        user = cursor.fetchone()
        if not user:
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        session_id = create_session(conn, user["id"], is_parent=0)
        redirect = RedirectResponse(url="/student/dashboard", status_code=status.HTTP_302_FOUND)
        set_auth_cookie(redirect, session_id)
        return redirect
    finally:
        conn.close()


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    portal_role: Optional[str] = Form(None),
    client_vault: Optional[str] = Form(None),
):
    conn = get_db_connection()
    try:
        hydrate_vault_cookie(request, conn, client_vault)
        raw_email = (email or "").strip()
        is_parent = (portal_role or "").strip().lower() == "parent"
        if raw_email.lower().startswith("p-"):
            is_parent = True
            raw_email = raw_email[2:].strip()

        norm_email = raw_email.lower() if "@" in raw_email else raw_email.replace(" ", "").replace("-", "")

        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE LOWER(email) = ? OR email = ?",
            (norm_email.lower(), raw_email),
        )
        user = cursor.fetchone()
        if not user or not verify_password(password[:72], user["password_hash"]):
            sync_users_from_blob(conn, force=True, target_email=norm_email)
            cursor.execute(
                "SELECT * FROM users WHERE LOWER(email) = ? OR email = ?",
                (norm_email.lower(), raw_email),
            )
            user = cursor.fetchone()

        if not user or not verify_password(password[:72], user["password_hash"]):
            return templates.TemplateResponse(
                request=request,
                name="auth/login.html",
                context={
                    "request": request,
                    "error": "Invalid Login ID or password.",
                    "email": raw_email,
                    "portal_role": "parent" if is_parent else "student",
                },
            )

        if is_parent and user["role"] == "student":
            if user["parent_locked"] == 1 and user["parent_pin"]:
                return _issue_parent_preauth_redirect(int(user["id"]))
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


@router.get("/auth/switch-to-student")
@router.post("/auth/switch-to-student")
async def switch_to_student(request: Request):
    conn = get_db_connection()
    try:
        user = security.get_current_user(request, conn)
        if not user or user.get("role") != "student":
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        session_id = create_session(conn, int(user["id"]), is_parent=0)
        redirect = RedirectResponse(url="/student/dashboard", status_code=status.HTTP_302_FOUND)
        set_auth_cookie(redirect, session_id)
        redirect.delete_cookie("parent_preauth")
        return redirect
    finally:
        conn.close()


@router.get("/auth/parent-portal")
@router.post("/auth/parent-portal")
async def switch_to_parent_portal(request: Request):
    conn = get_db_connection()
    try:
        user = security.get_current_user(request, conn)
        if not user:
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        if user.get("is_parent"):
            return RedirectResponse(url="/parent/dashboard", status_code=status.HTTP_302_FOUND)
        if user.get("role") == "student":
            if user.get("parent_locked") == 1 and user.get("parent_pin"):
                return _issue_parent_preauth_redirect(int(user["id"]), preserve_session=True)
            session_id = create_session(conn, int(user["id"]), is_parent=1)
            redirect = RedirectResponse(url="/parent/dashboard", status_code=status.HTTP_302_FOUND)
            set_auth_cookie(redirect, session_id)
            return redirect
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    finally:
        conn.close()


@router.get("/login/parent-pin", response_class=HTMLResponse)
async def parent_pin_page(request: Request, uid: int):
    preauth = request.cookies.get("parent_preauth") or request.cookies.get("__session")
    conn = get_db_connection()
    try:
        curr_user = security.get_current_user(request, conn)
        same_student = bool(curr_user and curr_user.get("role") == "student" and int(curr_user["id"]) == int(uid))
        if not _preauth_valid(preauth, uid) and not same_student:
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        has_student_session = bool(curr_user and curr_user.get("role") == "student")
        back_href = "/student/dashboard" if has_student_session and not curr_user.get("is_parent") else "/login"
        return templates.TemplateResponse(
            request=request,
            name="auth/parent_pin.html",
            context={"request": request, "uid": uid, "back_href": back_href},
        )
    finally:
        conn.close()


@router.post("/login/parent-pin")
async def parent_pin_submit(request: Request, uid: int = Form(...), pin: str = Form(...)):
    now = _time.time()
    preauth = request.cookies.get("parent_preauth") or request.cookies.get("__session")

    conn = get_db_connection()
    try:
        curr_user = security.get_current_user(request, conn)
        same_student = bool(curr_user and curr_user.get("role") == "student" and int(curr_user["id"]) == int(uid))
        if not _preauth_valid(preauth, uid) and not same_student:
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        has_student_session = bool(curr_user and curr_user.get("role") == "student" and not curr_user.get("is_parent"))
        back_href = "/student/dashboard" if has_student_session else "/login"

        attempt_info = _PARENT_PIN_ATTEMPTS.get(uid, [0, 0.0])
        if attempt_info[1] > now:
            wait_secs = int(attempt_info[1] - now)
            return templates.TemplateResponse(
                request=request,
                name="auth/parent_pin.html",
                context={
                    "request": request,
                    "uid": uid,
                    "back_href": back_href,
                    "error": f"Too many failed attempts. Please wait {wait_secs}s before trying again.",
                },
            )

        cursor = conn.cursor()
        cursor.execute("SELECT id, parent_pin FROM users WHERE id = ?", (uid,))
        user = cursor.fetchone()

        if not user or not _secrets.compare_digest(str(user["parent_pin"] or ""), str(pin or "").strip()):
            fails = int(attempt_info[0]) + 1
            if fails >= 5:
                _PARENT_PIN_ATTEMPTS[uid] = [0, now + 300]
                err_msg = "Incorrect PIN. Too many failed attempts — locked for 5 minutes."
            else:
                _PARENT_PIN_ATTEMPTS[uid] = [fails, 0.0]
                remaining = 5 - fails
                err_msg = f"Incorrect PIN. {remaining} {'attempt' if remaining == 1 else 'attempts'} remaining."
            return templates.TemplateResponse(
                request=request,
                name="auth/parent_pin.html",
                context={"request": request, "uid": uid, "back_href": back_href, "error": err_msg},
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
@router.get("/signup", response_class=HTMLResponse)
async def register_page(request: Request):
    conn = get_db_connection()
    try:
        classes = _fetch_classes(conn)
        q_cls = request.query_params.get("class_id")
        req_cls = int(q_cls) if (q_cls and q_cls.isdigit()) else None
        selected_class_id = _default_class_id(classes, req_cls)
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "request": request,
                "classes": classes,
                "selected_class_id": selected_class_id,
                "name": "",
                "email": "",
            },
        )
    finally:
        conn.close()


@router.post("/register")
@router.post("/signup")
async def register(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    confirm_password: Optional[str] = Form(None),
    class_id: Optional[int] = Form(None),
    client_vault: Optional[str] = Form(None),
):
    conn = get_db_connection()
    raw_name = (name or "").strip()
    raw_email = (email or "").strip()
    try:
        existing_vault = hydrate_vault_cookie(request, conn, client_vault)
        classes = _fetch_classes(conn)
        selected_class_id = _default_class_id(classes, class_id)

        def _render_err(msg: str) -> HTMLResponse:
            return templates.TemplateResponse(
                request=request,
                name="auth/register.html",
                context={
                    "request": request,
                    "error": msg,
                    "classes": classes,
                    "name": raw_name,
                    "email": raw_email,
                    "selected_class_id": selected_class_id,
                },
            )

        if not raw_name or not raw_email:
            return _render_err("Please enter both your student name and Login ID.")

        if len(password or "") < 6:
            return _render_err("Password must be at least 6 characters long.")

        if confirm_password is not None and password != confirm_password:
            return _render_err("Passwords do not match.")

        norm_email = raw_email.lower() if "@" in raw_email else raw_email.replace(" ", "").replace("-", "")
        clean_name = raw_name or norm_email.split("@")[0]

        cursor = conn.cursor()
        sync_users_from_blob(conn, force=True, target_email=norm_email)
        cursor.execute("SELECT id FROM users WHERE LOWER(email) = ?", (norm_email.lower(),))
        if cursor.fetchone():
            return _render_err("Login ID already registered. Log in instead.")

        cursor.execute("SELECT id FROM classes WHERE id = ?", (selected_class_id,))
        valid_cls = cursor.fetchone()
        if valid_cls:
            db_class_id = valid_cls["id"]
        else:
            db_class_id = _default_class_id(classes)

        hashed_pw = get_password_hash(password[:72])
        det_uid = deterministic_user_id(norm_email)
        user_record = {
            "id": det_uid,
            "name": clean_name,
            "email": norm_email,
            "password_hash": hashed_pw,
            "role": "student",
            "class_id": db_class_id,
        }
        created_row = ensure_user_row(conn, user_record)
        user_id = created_row["id"] if created_row else det_uid
        user_record["id"] = user_id
        save_user_to_blob(conn, user_record)

        session_id = create_session(conn, user_id, is_parent=0)
        redirect = RedirectResponse(url="/student/dashboard", status_code=status.HTTP_302_FOUND)
        set_auth_cookie(redirect, session_id)
        updated_vault = [
            u for u in existing_vault if str(u.get("email", "")).lower() != norm_email.lower()
        ] + [user_record]
        set_vault_cookie(redirect, updated_vault)
        return redirect
    except Exception as e:
        conn.rollback()
        print(f"Registration error: {e}")
        classes = []
        try:
            classes = _fetch_classes(conn)
        except Exception:
            pass
        selected_class_id = _default_class_id(classes, class_id)
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "request": request,
                "error": "Unable to complete registration. Please check your details and try again.",
                "classes": classes,
                "name": raw_name,
                "email": raw_email,
                "selected_class_id": selected_class_id,
            },
        )
    finally:
        conn.close()


@router.get("/logout")
@router.post("/logout")
async def logout(request: Request, response: Response):
    conn = get_db_connection()
    session_id = request.cookies.get("session_id") or request.cookies.get("__session")
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
    redirect.delete_cookie("parent_preauth", path="/")
    return redirect


@router.post("/set-theme")
async def set_theme(request: Request, theme: str = Form(...)):
    session_id = request.cookies.get("session_id") or request.cookies.get("__session")
    if session_id and theme in ("light", "dark"):
        conn = get_db_connection()
        try:
            conn.execute(
                """
                UPDATE users SET theme_preference = ?
                WHERE id = (SELECT user_id FROM sessions WHERE id = ?)
                """,
                (theme, session_id),
            )
            conn.commit()
        except Exception as e:
            print(f"Theme save error: {e}")
        finally:
            conn.close()
    return Response(status_code=status.HTTP_200_OK)
