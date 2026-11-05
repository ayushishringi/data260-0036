"""HW9 Part 1: Redis-backed view counter for the primary entity (VulnerabilityReport).

Every view is one Redis INCR on s0036:views:report:<id>. Only every 10th view touches MySQL,
where vulnerability_reports.view_count is set to the current Redis count.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import redis
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.kafka_common import PREFIX

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
SYNC_EVERY = 10

logger = logging.getLogger("s0036.hw9")


def get_redis() -> redis.Redis:
    """Redis client for the HW9 Redis Stack container (docker-compose.hw9.yml)."""

    return redis.Redis.from_url(REDIS_URL, decode_responses=False)


def views_key(report_id: int) -> str:
    """Redis key that holds the view count of one vulnerability report."""

    return f"{PREFIX}:views:report:{report_id}"


class ReportCache:
    """Redis cache in front of the s0036_rel vulnerability_reports table."""

    def __init__(self, redis_client: redis.Redis | None = None, engine: Engine | None = None) -> None:
        if engine is None:
            from backend.database import engine as default_engine
            engine = default_engine
        self.redis_client = redis_client or get_redis()
        self.engine = engine

    def increment_report_views(self, report_id: int) -> int:
        """Count one view of a report in Redis; every 10 views persist the count to the database."""

        key = views_key(report_id)
        count = int(self.redis_client.incr(key))
        if count % SYNC_EVERY == 0:
            with self.engine.begin() as conn:
                result = conn.execute(text("UPDATE vulnerability_reports SET view_count = :count WHERE id = :id"),
                                      {"count": count, "id": report_id})
            if result.rowcount:
                logger.info("✓ Synced views to database")
            else:
                logger.warning("report %s not found; view count %s not synced", report_id, count)
        return count

    def database_view_count(self, report_id: int) -> int | None:
        """view_count currently stored in MySQL (None if the report does not exist)."""

        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT view_count FROM vulnerability_reports WHERE id = :id"),
                               {"id": report_id}).first()
        return None if row is None else int(row.view_count)

    def reset_report_views(self, report_id: int) -> Any:
        """Delete the Redis counter (used to start a demo from zero)."""

        return self.redis_client.delete(views_key(report_id))
