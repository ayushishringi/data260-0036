"""JWT bearer authentication and role-based authorization (HW7 Part 1)."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User

ROLES = ("reader", "writer", "moderator")
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "s0036"
JWT_SECRET = os.getenv("HW7_JWT_SECRET", "local-dev-only-s0036-change-me-in-production")
ACCESS_TOKEN_MINUTES = int(os.getenv("HW7_ACCESS_TOKEN_MINUTES", "30"))

bearer_scheme = HTTPBearer(auto_error=False)


def unauthorized(detail: str) -> HTTPException:
    """401 with the WWW-Authenticate header that bearer-token clients expect."""

    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_access_token(user: User, expires_in: timedelta | None = None) -> str:
    """Sign a short-lived access token carrying the user's id, username and role."""

    now = datetime.now(timezone.utc)
    claims = {
        "sub": user.username,
        "uid": user.id,
        "role": user.role,
        "iss": JWT_ISSUER,
        "iat": now,
        "exp": now + (expires_in or timedelta(minutes=ACCESS_TOKEN_MINUTES)),
    }
    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify signature, expiry and issuer; raise 401 for any invalid token."""

    try:
        return jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["sub", "role", "exp", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise unauthorized("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise unauthorized("Invalid token") from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the bearer token to a user that still exists in MySQL."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized("Not authenticated")
    claims = decode_access_token(credentials.credentials)
    user = db.scalar(select(User).where(User.username == claims["sub"]))
    if user is None:
        raise unauthorized("Invalid token")
    return user


def require_roles(*allowed: str) -> Callable[..., User]:
    """Dependency factory: 401 without a valid token, 403 when the role is not allowed.

    The role is read from the database, not the token, so a demotion takes effect immediately.
    """

    unknown = set(allowed) - set(ROLES)
    if unknown:
        raise ValueError(f"unknown roles: {sorted(unknown)}")

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not allowed; requires one of: {', '.join(allowed)}",
            )
        return user

    return dependency


any_authenticated = require_roles("reader", "writer", "moderator")
writer_or_moderator = require_roles("writer", "moderator")
moderator_only = require_roles("moderator")
