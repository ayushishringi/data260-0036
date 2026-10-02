from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger("s0036_domain_mcp")
VERIFY_SEED = 260036
ENVELOPE_KEYS = ("ok", "data", "error")


def envelope(ok: bool, data: Any = None, error: str | None = None) -> dict[str, Any]:
    return {"ok": ok, "data": data if ok else None, "error": error if not ok else None}


@dataclass
class DomainStore:
    records: list[dict[str, Any]]

    @classmethod
    def fixture(cls) -> "DomainStore":
        return cls([
            {"id": 1, "package": "openssl", "severity": "critical", "available_count": 1,
             "advisory_code": "CVE-2024-9999"},
            {"id": 2, "package": "lodash", "severity": "high", "available_count": 3,
             "advisory_code": "GHSA-demo-1234"},
        ])

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return envelope(False, error="query must be a non-empty string")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 25:
            return envelope(False, error="limit must be an integer from 1 to 25")
        needle = query.strip().lower()
        return envelope(True, [r for r in self.records if needle in r["package"].lower()][:limit])

    def detail(self, id: int | str) -> dict[str, Any]:
        try:
            record_id = int(id)
        except (TypeError, ValueError):
            return envelope(False, error="id must be an integer")
        record = next((r for r in self.records if r["id"] == record_id), None)
        return envelope(True, record) if record else envelope(False, error="record not found")

    def aggregate(self, severity: str | None = None) -> dict[str, Any]:
        if severity is not None and severity not in {"critical", "high", "medium", "low"}:
            return envelope(False, error="severity must be critical, high, medium, or low")
        rows = [r for r in self.records if severity is None or r["severity"] == severity]
        return envelope(True, {
            "count": len(rows),
            "available_count_total": sum(r["available_count"] for r in rows),
            "by_severity": {level: sum(r["severity"] == level for r in rows)
                            for level in ("critical", "high", "medium", "low")},
        })


def execute_tool(name: str, inputs: dict[str, Any] | None, store: DomainStore | None = None) -> str:
    """The only entry point exposed to the Part 5 agent."""
    store = store or DomainStore.fixture()
    inputs = inputs or {}
    try:
        # Safety rule: aggregate calls cannot request a negative inventory view.
        if name == "aggregate" and inputs.get("include_unavailable") is True:
            return json.dumps(envelope(False, error="safety rule: unavailable inventory is restricted"))
        handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "search": store.search,
            "detail": store.detail,
            "aggregate": store.aggregate,
        }
        if name not in handlers:
            return json.dumps(envelope(False, error=f"unknown tool: {name}"))
        return json.dumps(handlers[name](**inputs), sort_keys=True)
    except TypeError as exc:
        return json.dumps(envelope(False, error=f"invalid inputs: {exc}"), sort_keys=True)
    except Exception as exc:  # tool boundary must never crash its caller
        LOGGER.exception("tool failure")
        return json.dumps(envelope(False, error=f"tool failure: {exc}"), sort_keys=True)


def retry_operation(operation: Callable[[], Any], *, attempts: int = 3,
                    timeout_seconds: float = 2.0, backoff_seconds: float = 0.01) -> tuple[Any, int, float]:
    started = time.perf_counter()
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            value = operation()
            return value, attempt, (time.perf_counter() - started) * 1000
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(min(backoff_seconds * (2 ** (attempt - 1)), timeout_seconds))
    raise RuntimeError(f"operation failed after {attempts} attempts: {last_error}")


def fault_injection_call(rate: float, call_index: int, seed: int = VERIFY_SEED) -> dict[str, Any]:
    rng = random.Random(seed + call_index)
    failures = 0

    def flaky() -> str:
        nonlocal failures
        if rng.random() < rate:
            failures += 1
            raise OSError("injected transient failure")
        return "ok"

    started = time.perf_counter()
    try:
        value, attempts, _ = retry_operation(flaky)
        status, error = "success", None
    except RuntimeError as exc:
        value, attempts, error = None, 3, str(exc)
        status = "failure"
    return {"rate": rate, "call": call_index, "status": status, "attempts": attempts,
            "injected_failures": failures, "latency_ms": round((time.perf_counter() - started) * 1000, 4),
            "result": value, "error": error}
