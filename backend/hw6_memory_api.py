from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from backend.hw6_memory_service import get_aggregate, get_memory, make_chat_turn
from src.model_client import ModelClient


router = APIRouter(prefix="/api", tags=["HW6 memory"])


class ChatRequest(BaseModel):
    user_id: str = Field(min_length=1)
    session_id: str | None = None
    message: str = Field(min_length=1)


@router.post("/chat")
def chat(payload: ChatRequest) -> dict:
    try:
        return make_chat_turn(
            payload.user_id.strip(),
            payload.session_id.strip() if payload.session_id else None,
            payload.message.strip(),
            ModelClient(),
        )
    except (PyMongoError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/memory/{user_id}")
def memory(user_id: str) -> dict:
    try:
        return get_memory(user_id.strip())
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="MongoDB is unavailable") from exc


@router.get("/aggregate/{user_id}")
def aggregate(user_id: str) -> dict:
    try:
        return get_aggregate(user_id.strip())
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="MongoDB is unavailable") from exc
