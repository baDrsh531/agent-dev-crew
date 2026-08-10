"""Reference solution — JWT authentication."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request

ALGORITHM = "HS256"
DEFAULT_SECRET = "dev-secret"


def _secret() -> str:
    return os.environ.get("JWT_SECRET", DEFAULT_SECRET)


def create_access_token(subject: str, role: str = "user", expires_in: int = 3600) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    return jwt.encode(claims, _secret(), algorithm=ALGORITHM)


def current_claims(request: Request) -> dict:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid or expired token") from None


def require_admin(claims: dict = Depends(current_claims)) -> dict:
    # 403 rather than 401: the caller is authenticated, just not permitted.
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return claims
