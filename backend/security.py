import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import LoginSession, User


SESSION_COOKIE_NAME = "session_token"
SESSION_DURATION = timedelta(minutes=30)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)

    password_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        240_000,
    )

    return f"{salt.hex()}${password_digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, digest_hex = stored_hash.split("$", maxsplit=1)

        salt = bytes.fromhex(salt_hex)
        expected_digest = bytes.fromhex(digest_hex)

        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            240_000,
        )

        return hmac.compare_digest(actual_digest, expected_digest)

    except (ValueError, TypeError):
        return False


def create_server_session(db: Session, user: User) -> str:
    current_time = datetime.now(timezone.utc).replace(tzinfo=None)
    session_token = secrets.token_urlsafe(48)

    database_session = LoginSession(
        id=session_token,
        user_id=user.id,
        created_at=current_time,
        expires_at=current_time + SESSION_DURATION,
    )

    db.add(database_session)
    db.commit()

    return session_token


def get_current_user(
    session_token: str | None = Cookie(
        default=None,
        alias=SESSION_COOKIE_NAME,
    ),
    db: Session = Depends(get_db),
) -> User:
    if not session_token:
        raise HTTPException(
            status_code=401,
            detail="Login required",
        )

    current_time = datetime.now(timezone.utc).replace(tzinfo=None)

    database_session = db.scalar(
        select(LoginSession).where(
            LoginSession.id == session_token,
            LoginSession.expires_at > current_time,
        )
    )

    if database_session is None:
        raise HTTPException(
            status_code=401,
            detail="Login required",
        )

    user = db.get(User, database_session.user_id)

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Login required",
        )

    return user