import time
import os
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


ROOT = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(ROOT / "templates"))

router = APIRouter()

USERS = {
    "ayushi": {
        "password": "data260",
        "name": "Ayushi Shringi",
    }
}

IDLE_TIMEOUT_SECONDS = int(
    os.getenv("SESSION_IDLE_TIMEOUT", "900")
)


def get_current_user(request: Request):
    user = request.session.get("user")
    last_seen = request.session.get("last_seen")

    if user is None or last_seen is None:
        request.session.clear()
        return None

    if time.time() - float(last_seen) > IDLE_TIMEOUT_SECONDS:
        request.session.clear()
        return None

    request.session["last_seen"] = time.time()
    return user


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "user": get_current_user(request),
        },
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "user": get_current_user(request),
            "error": None,
        },
    )


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    account = USERS.get(username.strip().lower())

    if account is None or account["password"] != password:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "user": None,
                "error": "Invalid username or password.",
            },
            status_code=401,
        )

    request.session["user"] = {
        "username": username.strip().lower(),
        "name": account["name"],
    }

    request.session["last_seen"] = time.time()

    return RedirectResponse("/dashboard", status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = get_current_user(request)

    if user is None:
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
        },
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)