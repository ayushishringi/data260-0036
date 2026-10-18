from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


Role = Literal["user", "assistant"]
SummaryScope = Literal["session", "user"]


class MessageRecord(BaseModel):
    user_id: str = Field(min_length=1)
    session_id: str | None = None
    role: Role
    content: str = Field(min_length=1)
    created_at: datetime

    @field_validator("user_id", "content")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


class SummaryRecord(BaseModel):
    user_id: str = Field(min_length=1)
    session_id: str | None = None
    scope: SummaryScope
    text: str = Field(min_length=1)
    created_at: datetime


class EpisodeRecord(BaseModel):
    user_id: str = Field(min_length=1)
    session_id: str | None = None
    fact: str = Field(min_length=1, max_length=500)
    importance: float = Field(ge=0, le=1)
    embedding: list[float]
    created_at: datetime
