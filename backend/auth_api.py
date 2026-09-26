from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import LoginSession, User
from backend.schemas import LoginRequest, RegisterRequest
from backend.security import (
    SESSION_COOKIE_NAME,
    create_server_session,
    get_current_user,
    hash_password,
    verify_password,
)


router = APIRouter(
    prefix="/api/auth",
    tags=["authentication"],
)


@router.post("/register", status_code=201)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> dict:
    existing_user = db.scalar(
        select(User).where(User.email == payload.email)
    )

    if existing_user is not None:
        raise HTTPException(
            status_code=409,
            detail="Email already registered",
        )

    user = User(
        name=payload.name.strip(),
        email=str(payload.email),
        password_hash=hash_password(payload.password),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
    }


@router.post("/login")
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    user = db.scalar(
        select(User).where(User.email == payload.email)
    )

    if user is None or not verify_password(
        payload.password,
        user.password_hash,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    session_token = create_server_session(db, user)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=1800,
    )

    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
    }


@router.get("/me")
def get_me(
    current_user: User = Depends(get_current_user),
) -> dict:
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
    }


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    session_token: str | None = Cookie(
        default=None,
        alias=SESSION_COOKIE_NAME,
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if session_token is not None:
        database_session = db.get(
            LoginSession,
            session_token,
        )

        if database_session is not None:
            db.delete(database_session)
            db.commit()

    response.delete_cookie(SESSION_COOKIE_NAME)