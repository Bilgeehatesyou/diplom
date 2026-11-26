"""
JWT (HS256) нэвтрэлт + bcrypt нууц үг + role-based access control.

- REST: `Authorization: Bearer <token>` header.
- WebSocket: browser WS-д header тавих боломжгүй тул `?token=<token>` query.
- student_id / teacher-ийг token-ий `sub`-аас авна (URL path-аас биш), тиймээс
  нэг оюутан нөгөөгийн нэрээр, эсвэл "teacher" нэрээр холбогдох боломжгүй.
"""
import os
import secrets
import time
from typing import Literal

import bcrypt
import jwt
from fastapi import Header, HTTPException

from utils.log import log_warn

Role = Literal["student", "teacher"]

_ALGO = "HS256"
TOKEN_TTL_SEC = int(os.getenv("TOKEN_TTL_SEC", str(6 * 3600)))

_SECRET = os.getenv("SECRET_KEY") or ""
if len(_SECRET) < 16:
    # .env байхгүй үед dev-д ажиллахаар түр түлхүүр үүсгэнэ (restart хийхэд token хүчингүй болно).
    _SECRET = secrets.token_urlsafe(48)
    log_warn("AUTH", "SECRET_KEY тохируулаагүй/богино — түр түлхүүр үүсгэлээ (backend/.env-д SECRET_KEY тавина уу)")


# ── Password hashing ──────────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def is_hashed(value: str) -> bool:
    return value.startswith(("$2a$", "$2b$", "$2y$"))


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed or not is_hashed(hashed):
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


# ── Tokens ────────────────────────────────────────────────────────────────────
def issue_token(sub: str, role: Role, name: str = "") -> str:
    now = int(time.time())
    payload = {"sub": str(sub), "role": role, "name": name, "iat": now, "exp": now + TOKEN_TTL_SEC}
    return jwt.encode(payload, _SECRET, algorithm=_ALGO)


def decode_token(token: str | None) -> dict | None:
    if not token:
        return None
    if token.startswith("Bearer "):
        token = token[len("Bearer "):]
    try:
        claims = jwt.decode(token, _SECRET, algorithms=[_ALGO], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None
    if claims.get("role") not in ("student", "teacher"):
        return None
    return claims


def require(role: Role):
    """FastAPI dependency: `user = Depends(require("teacher"))`."""
    def dep(authorization: str | None = Header(default=None)) -> dict:
        claims = decode_token(authorization)
        if claims is None:
            raise HTTPException(401, "Нэвтрэх шаардлагатай")
        if claims["role"] != role:
            raise HTTPException(403, "Хандах эрхгүй")
        return claims
    return dep


require_student = require("student")
require_teacher = require("teacher")
