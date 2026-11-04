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

def create_session(conn, user_id: int, expires_days: int = 7, is_parent: int = 0) -> str:
    session_id = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_days)).isoformat()
    
    conn.execute(
        "INSERT INTO sessions (id, user_id, expires_at, is_parent) VALUES (?, ?, ?, ?)",
        (session_id, user_id, expires_at, is_parent)
    )
    conn.commit()
    return session_id

def get_current_user(request: Request, conn):
    session_id = request.cookies.get("session_id")
    if not session_id:
        return None
        
    # Check session
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.*, s.is_parent FROM users u
        JOIN sessions s ON u.id = s.user_id
        WHERE s.id = ? AND s.expires_at > ?
    """, (session_id, datetime.now(timezone.utc).isoformat()))
    
    user = cursor.fetchone()
    if not user:
        return None
    
    return dict(user)

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
    is_production = os.environ.get("K_SERVICE") is not None  # Set by Cloud Run
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        max_age=expires_days * 24 * 60 * 60,
        samesite="lax",
        secure=is_production
    )

def remove_auth_cookie(response: Response):
    response.delete_cookie("session_id")
