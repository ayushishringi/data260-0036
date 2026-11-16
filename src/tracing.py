"""HW10 Part 4: structured JSON spans, one line per stage, keyed by the HW8 correlation_id.

trace_id IS the correlation_id: it is created once (before the cache lookup) and carried in every
Kafka message (inbox, tasks, drafts, final) and into the evaluator. No second identifier exists.

Every process appends to the same file (HW10_SPAN_FILE, default reports/hw10/traces/spans.jsonl);
an flock around each append keeps lines whole when the agents write at the same time.
Spans are only written when HW10_TRACE=1, so the HW8/HW9 scripts behave exactly as before.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPAN_FILE = ROOT / "reports" / "hw10" / "traces" / "spans.jsonl"

# Stage names in request order (queue_* = time a message waited in a topic before its consumer read it).
STAGE_ORDER = ["request", "cache_lookup", "queue_inbox", "planner", "queue_tasks", "writer", "queue_drafts",
               "reviewer", "queue_final", "dead_letter", "cache_store", "evaluation"]
QUEUE_STAGE = {"s0036_inbox": "queue_inbox", "s0036_tasks": "queue_tasks", "s0036_drafts": "queue_drafts",
               "s0036_final": "queue_final"}


def enabled() -> bool:
    return os.getenv("HW10_TRACE", "0") == "1"


def span_file() -> Path:
    return Path(os.getenv("HW10_SPAN_FILE", DEFAULT_SPAN_FILE))


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="milliseconds")


def write_span(trace_id: str | None, stage: str, start: float, end: float, status: str = "ok",
               error: str | None = None, component: str | None = None, **attrs: Any) -> dict[str, Any] | None:
    """Append one span (start/end are epoch seconds); returns it, or None when tracing is off."""

    if not enabled() or not trace_id:
        return None
    record = {"trace_id": trace_id, "span_id": uuid.uuid4().hex[:16], "stage": stage,
              "start_time": iso(start), "end_time": iso(end), "start_ts": round(start, 6), "end_ts": round(end, 6),
              "duration_ms": round((end - start) * 1000, 2), "status": status, "error": error,
              "component": component or stage, **attrs}
    path = span_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps(record, default=str) + "\n")
        fcntl.flock(stream, fcntl.LOCK_UN)
    return record


@contextmanager
def span(trace_id: str | None, stage: str, component: str | None = None, **attrs: Any) -> Iterator[dict[str, Any]]:
    """Time a block as one span; an exception marks it status=error (and is re-raised).

    The yielded dict can be filled with more attributes while the block runs.
    """

    extra: dict[str, Any] = dict(attrs)
    start = time.time()
    try:
        yield extra
    except Exception as exc:
        write_span(trace_id, stage, start, time.time(), "error", f"{type(exc).__name__}: {exc}", component, **extra)
        raise
    write_span(trace_id, stage, start, time.time(), extra.pop("status", "ok"), extra.pop("error", None),
               component, **extra)


def load_spans(path: Path | None = None) -> list[dict[str, Any]]:
    """Every span in the file (unparseable lines are skipped)."""

    path = path or span_file()
    if not path.exists():
        return []
    spans = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            spans.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return spans


def trace(spans: list[dict[str, Any]], trace_id: str) -> list[dict[str, Any]]:
    """The spans of one trace in the order they started."""

    return sorted((s for s in spans if s.get("trace_id") == trace_id),
                  key=lambda s: (s["start_ts"], STAGE_ORDER.index(s["stage"]) if s["stage"] in STAGE_ORDER else 99))
