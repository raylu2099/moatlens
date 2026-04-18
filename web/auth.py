"""
Session auth for web interface.
bcrypt for passwords, itsdangerous for signed session cookies.
"""
from __future__ import annotations

from fastapi import Cookie, HTTPException, Request
from itsdangerous import BadSignature, URLSafeSerializer
from passlib.context import CryptContext

from shared.config import Config
from shared.db import get_user_by_id


pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(pw: str) -> str:
    return pwd_ctx.hash(pw)


def verify_password(pw: str, pw_hash: str) -> bool:
    try:
        return pwd_ctx.verify(pw, pw_hash)
    except Exception:
        return False


def session_serializer(cfg: Config) -> URLSafeSerializer:
    return URLSafeSerializer(cfg.secret_key, salt="moatlens-session")


def issue_session_cookie(cfg: Config, user_id: int) -> str:
    return session_serializer(cfg).dumps({"uid": user_id})


def read_session(cfg: Config, cookie_value: str | None) -> int | None:
    if not cookie_value:
        return None
    try:
        data = session_serializer(cfg).loads(cookie_value)
        return int(data.get("uid"))
    except (BadSignature, ValueError, KeyError):
        return None


def current_user(request: Request, cfg: Config) -> dict | None:
    """Return user dict if authenticated, else None."""
    uid = read_session(cfg, request.cookies.get("session"))
    if uid is None:
        return None
    return get_user_by_id(cfg, uid)


def require_user(request: Request, cfg: Config) -> dict:
    user = current_user(request, cfg)
    if not user:
        raise HTTPException(status_code=302, detail="/login", headers={"Location": "/login"})
    return user
