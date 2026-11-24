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


# ---- Registration form options (same fields as the saxaz.com enrolment form) ----
_SYLLABUS_OPTIONS = ["CBSE", "Kerala State (SCERT)", "ICSE", "Other State Board", "Other"]
_MEDIUM_OPTIONS = ["English", "Malayalam", "Hindi", "Tamil", "Other"]
_RELATIONSHIP_OPTIONS = ["Mother", "Father", "Guardian", "Other"]
_COUNTRY_OPTIONS = ["India", "United Arab Emirates", "Saudi Arabia", "Qatar", "Oman", "Kuwait", "Bahrain", "Other"]
_INDIA_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi",
    "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]
# District dropdown where we have the official list; other states type the district.
_DISTRICTS_BY_STATE = {
    "Kerala": [
        "Thiruvananthapuram", "Kollam", "Pathanamthitta", "Alappuzha", "Kottayam", "Idukki", "Ernakulam",
        "Thrissur", "Palakkad", "Malappuram", "Kozhikode", "Wayanad", "Kannur", "Kasaragod",
    ],
}


def _register_context(request: Request, classes: list[dict], form: Optional[dict] = None, error: Optional[str] = None) -> dict:
    ctx = {
        "request": request,
        "classes": classes,
        "form": form or {},
        "syllabus_options": _SYLLABUS_OPTIONS,
        "medium_options": _MEDIUM_OPTIONS,
        "relationship_options": _RELATIONSHIP_OPTIONS,
        "country_options": _COUNTRY_OPTIONS,
        "india_states": _INDIA_STATES,
        "districts_by_state": _DISTRICTS_BY_STATE,
    }
    if error:
        ctx["error"] = error
    return ctx


def _class_id_for_grade(classes: list[dict], grade: Optional[int]) -> int:
    """Map the chosen class number (1-12) to a content class row ("Grade 10", ...); falls back to the default."""
    if grade:
        for c in classes:
            if str(c.get("name") or "").strip().lower() in (f"grade {grade}", f"class {grade}"):
                return int(c["id"])
    return _default_class_id(classes)


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
        q_cls = request.query_params.get("class")
        form = {"chosen_class": q_cls} if (q_cls and q_cls.isdigit() and 1 <= int(q_cls) <= 12) else {}
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context=_register_context(request, classes, form),
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
    chosen_class: str = Form(""),
    syllabus: str = Form(""),
    medium: str = Form(""),
    country: str = Form("India"),
    state: str = Form(""),
    district: str = Form(""),
    school: str = Form(""),
    parent_name: str = Form(""),
    parent_phone: str = Form(""),
    parent_email: str = Form(""),
    parent_relationship: str = Form(""),
    class_id: Optional[int] = Form(None),
    client_vault: Optional[str] = Form(None),
):
    import re as _re
    conn = get_db_connection()
    clip = lambda v, n: (v or "").strip()[:n]
    form = {
        "name": clip(name, 80),
        "email": clip(email, 120),
        "chosen_class": clip(chosen_class, 2),
        "syllabus": clip(syllabus, 40),
        "medium": clip(medium, 40),
        "country": clip(country, 60) or "India",
        "state": clip(state, 80),
        "district": clip(district, 80),
        "school": clip(school, 120),
        "parent_name": clip(parent_name, 80),
        "parent_phone": clip(parent_phone, 18),
        "parent_email": clip(parent_email, 120),
        "parent_relationship": clip(parent_relationship, 20),
    }
    classes: list[dict] = []
    try:
        existing_vault = hydrate_vault_cookie(request, conn, client_vault)
        classes = _fetch_classes(conn)

        def _render_err(msg: str) -> HTMLResponse:
            return templates.TemplateResponse(
                request=request, name="auth/register.html", context=_register_context(request, classes, form, msg)
            )

        # ---- validation (kid / parent friendly messages) ----
        if not form["name"]:
            return _render_err("Please enter the student's name.")
        grade = int(form["chosen_class"]) if form["chosen_class"].isdigit() else 0
        if not (1 <= grade <= 12):
            return _render_err("Please choose the student's class (1 to 12).")
        if form["syllabus"] not in _SYLLABUS_OPTIONS:
            return _render_err("Please choose the syllabus.")
        if form["medium"] not in _MEDIUM_OPTIONS:
            return _render_err("Please choose the medium.")
        if form["country"] not in _COUNTRY_OPTIONS:
            form["country"] = "Other"
        if form["country"] == "India" and form["state"] and form["state"] not in _INDIA_STATES:
            return _render_err("Please choose a state from the list.")
        if not form["parent_name"]:
            return _render_err("Please enter the parent or guardian's name.")
        phone_digits = _re.sub(r"\D", "", form["parent_phone"])
        if form["country"] == "India":
            if phone_digits.startswith("91") and len(phone_digits) == 12:
                phone_digits = phone_digits[2:]
            if len(phone_digits) != 10:
                return _render_err("Please enter the parent's 10-digit mobile number.")
            stored_phone = "+91" + phone_digits
        else:
            if not (7 <= len(phone_digits) <= 15):
                return _render_err("Please enter the parent's phone number with country code.")
            stored_phone = "+" + phone_digits
        if form["parent_email"] and not _re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", form["parent_email"]):
            return _render_err("The parent email doesn't look right. Please check it.")
        if form["parent_relationship"] and form["parent_relationship"] not in _RELATIONSHIP_OPTIONS:
            form["parent_relationship"] = ""
        raw_email = form["email"]
        if not raw_email:
            return _render_err("Please enter a phone number or email to use as the Login ID.")
        if "@" in raw_email:
            if not _re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw_email):
                return _render_err("The Login ID email doesn't look right. Please check it.")
        elif not (7 <= len(_re.sub(r"\D", "", raw_email)) <= 15) or _re.search(r"[^\d+\s()-]", raw_email):
            return _render_err("The Login ID must be a valid email address or phone number.")
        if len(password or "") < 8:
            return _render_err("Password must be at least 8 characters long.")
        if confirm_password is not None and password != confirm_password:
            return _render_err("Passwords do not match.")

        norm_email = raw_email.lower() if "@" in raw_email else _re.sub(r"[\s()-]", "", raw_email)
        clean_name = form["name"]

        cursor = conn.cursor()
        sync_users_from_blob(conn, force=True, target_email=norm_email)
        cursor.execute("SELECT id FROM users WHERE LOWER(email) = ?", (norm_email.lower(),))
        if cursor.fetchone():
            return _render_err("This Login ID is already registered. Log in instead.")

        db_class_id = _class_id_for_grade(classes, grade)

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

        # Enrolment details from the form
        cursor.execute(
            """UPDATE users SET chosen_class = ?, syllabus = ?, medium = ?, country = ?, state = ?, district = ?,
                   school = ?, parent_name = ?, parent_phone = ?, parent_email = ?, parent_relationship = ?
               WHERE id = ?""",
            (str(grade), form["syllabus"], form["medium"], form["country"], form["state"] or None,
             form["district"] or None, form["school"] or None, form["parent_name"], stored_phone,
             (form["parent_email"].lower() or None), form["parent_relationship"] or None, user_id),
        )
        conn.commit()
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
        try:
            classes = classes or _fetch_classes(conn)
        except Exception:
            pass
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context=_register_context(request, classes, form, "Unable to complete registration. Please check your details and try again."),
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
    """Save the display mode (light / dark / reading) on the signed-in account."""
    if theme not in ("light", "reading"):
        return Response(status_code=status.HTTP_400_BAD_REQUEST)
    conn = get_db_connection()
    try:
        user = security.get_current_user(request, conn)
        if not user:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        conn.execute("UPDATE users SET theme_preference = ? WHERE id = ?", (theme, int(user["id"])))
        conn.commit()
    except Exception as e:
        print(f"Theme save error: {e}")
    finally:
        conn.close()
    return Response(status_code=status.HTTP_200_OK)
