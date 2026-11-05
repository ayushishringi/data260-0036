"""HW9: HTTP ingress for the domain Q&A endpoint, with the semantic cache in front of the HW8 agents.

POST /api/qa {"question": "...", "threshold": 0.85}  -> answer + is_cached + similarity + latency_ms
POST /api/reports/{report_id}/views                 -> Part 1 view counter
The Planner/Writer/Reviewer must be running (grounded: HW8_GROUNDED=1 HW8_GROUP_SUFFIX=_hw9).
Port 8037 because the HW8 Kafka API container already serves PORT_BASE 8036.
Run: make qa-api-hw09
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.hw9_pipeline import PipelineClient
from src.redis_store import ReportCache, get_redis
from src.semantic_cache import DEFAULT_THRESHOLD, CachedQA, Embedder, SemanticCache

state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Load the embedding model and connect to Redis and Kafka once at startup."""

    redis_client = get_redis()
    pipeline = PipelineClient()
    state["qa"] = CachedQA(SemanticCache(redis_client), Embedder(), pipeline)
    state["views"] = ReportCache(redis_client)
    yield
    pipeline.close()


app = FastAPI(title="s0036 HW9 cached Q&A", lifespan=lifespan)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    threshold: float = Field(default=DEFAULT_THRESHOLD, ge=0.0, le=1.0)


@app.post("/api/qa")
def ask(body: Question) -> dict[str, Any]:
    """Answer through the semantic cache; a miss runs the HW8 agent pipeline."""

    try:
        result = state["qa"].ask(body.question, threshold=body.threshold)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    keys = ("answer", "is_cached", "similarity", "latency_ms", "matched_query", "threshold", "data_version",
            "timings")
    return {k: result.get(k) for k in keys}


@app.post("/api/reports/{report_id}/views")
def view(report_id: int) -> dict[str, int]:
    """Count one view of a vulnerability report (Redis INCR, synced to MySQL every 10)."""

    return {"report_id": report_id, "views": state["views"].increment_report_views(report_id)}
