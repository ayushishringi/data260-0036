"""JWT login and identity routes (HW7). The HW4 cookie-session routes live only at the hw4 tag."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.jwt_auth import ACCESS_TOKEN_MINUTES, create_access_token, get_current_user, unauthorized
from backend.models import User
from backend.schemas import LoginRequest
from backend.security import verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    """Verify the password hash stored in MySQL, then issue a JWT access token."""

    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise unauthorized("Invalid username or password")
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_MINUTES * 60,
        "role": user.role,
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    """Return the authenticated user's identity and role."""

    return {"id": user.id, "username": user.username, "role": user.role}
