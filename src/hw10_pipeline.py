"""HW10: traced request path = semantic cache (HW9) -> Kafka agents (HW8) -> evaluator.

TracedPipelineClient sends a question to s0036_inbox with correlation_id = trace_id and returns the
s0036_final message with that id, or raises PipelineFailed as soon as the same id shows up on
s0036_dead_letter. It also keeps the plan and draft messages it sees for the id (s0036_tasks,
s0036_drafts), which build_hw10_eval_cases.py freezes into eval_cases.json.

traced_request() wraps one CachedQA.ask in the root `request` span (hit / miss / error).
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

from confluent_kafka import TopicPartition

from src import tracing
from src.hw9_pipeline import AgentStack
from src.kafka_common import (
    DEAD_LETTER_TOPIC,
    DRAFTS_TOPIC,
    FINAL_TOPIC,
    INBOX_TOPIC,
    TASKS_TOPIC,
    decode,
    make_consumer,
    make_producer,
    now_iso,
    produce_json,
)

ROOT = Path(__file__).resolve().parents[1]
HW10_DIR = ROOT / "reports" / "hw10"
HW10_ENV = {"HW10_TRACE": "1", "HW10_FAULTS": "1", "HW10_SPAN_FILE": str(tracing.span_file())}


class PipelineFailed(RuntimeError):
    """The request reached s0036_dead_letter instead of s0036_final."""

    def __init__(self, dead: dict[str, Any]) -> None:
        self.dead = dead
        super().__init__(f"{dead.get('failed_agent')} failed after {dead.get('attempts')} attempts: {dead.get('error')}")


def assign_all_at_end(consumer: Any, topics: list[str]) -> None:
    """Assign every partition of every topic at its current high watermark."""

    partitions = []
    for topic in topics:
        metadata = consumer.list_topics(topic, timeout=10)
        for pid in metadata.topics[topic].partitions:
            _low, high = consumer.get_watermark_offsets(TopicPartition(topic, pid), timeout=10)
            partitions.append(TopicPartition(topic, pid, high))
    consumer.assign(partitions)


class TracedPipelineClient:
    """HW8 pipeline client whose correlation_id is supplied by the caller (the trace_id)."""

    def __init__(self) -> None:
        self.producer = make_producer()
        self.reader = make_consumer(f"s0036_hw10_reader_{uuid.uuid4().hex[:8]}", offset_reset="latest")
        assign_all_at_end(self.reader, [TASKS_TOPIC, DRAFTS_TOPIC, FINAL_TOPIC, DEAD_LETTER_TOPIC])
        self.seen: dict[str, dict[str, Any]] = {}  # correlation_id -> {"plan": msg, "draft": msg}
        self.inject_fault: str | None = None  # set for one call by the failed-trace demo

    def ask(self, question: str, timeout: float = 300, correlation_id: str | None = None) -> dict[str, Any]:
        cid = correlation_id or str(uuid.uuid4())
        message = {"correlation_id": cid, "trace_id": cid, "kind": "question", "question": question,
                   "asked_at": now_iso()}
        if self.inject_fault:
            message["inject_fault"] = self.inject_fault
        produce_json(self.producer, INBOX_TOPIC, message, key=cid)
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.reader.poll(1.0)
            if msg is None or msg.error():
                continue
            try:
                payload = decode(msg)
            except (ValueError, UnicodeDecodeError):
                continue
            if payload.get("correlation_id") != cid:
                continue
            topic = msg.topic()
            if topic == TASKS_TOPIC:
                self.seen.setdefault(cid, {})["plan"] = payload
            elif topic == DRAFTS_TOPIC:
                self.seen.setdefault(cid, {})["draft"] = payload
            elif topic == DEAD_LETTER_TOPIC:
                raise PipelineFailed(payload)
            elif topic == FINAL_TOPIC:
                return payload
        raise TimeoutError(f"no final answer for correlation_id {cid} within {timeout}s")

    def close(self) -> None:
        self.reader.close()


def traced_request(qa: Any, question: str, trace_id: str | None = None, **attrs: Any) -> dict[str, Any]:
    """Run one question through CachedQA under a root `request` span; never raises."""

    trace_id = trace_id or str(uuid.uuid4())
    start = time.time()
    try:
        result = qa.ask(question, trace_id=trace_id)
    except Exception as exc:
        failed = getattr(exc, "dead", {}).get("failed_agent") if isinstance(exc, PipelineFailed) else None
        error = f"{type(exc).__name__}: {exc}"
        tracing.write_span(trace_id, "request", start, time.time(), "error", error, "client", question=question,
                           path="miss", failed_stage=failed, **attrs)
        return {"trace_id": trace_id, "question": question, "status": "error", "error": error,
                "failed_stage": failed, "is_cached": False, "latency_ms": round((time.time() - start) * 1000, 2)}
    path = "hit" if result["is_cached"] else "miss"
    tracing.write_span(trace_id, "request", start, time.time(), "ok", None, "client", question=question, path=path,
                       similarity=result.get("similarity"), **attrs)
    return {"trace_id": trace_id, **result, "review_status": result.get("status"), "status": "ok"}


def wait_for_evaluation(trace_id: str, timeout: float = 1200) -> dict[str, Any] | None:
    """Block until the evaluator has written the `evaluation` span for this trace."""

    deadline = time.time() + timeout
    while time.time() < deadline:
        for s in reversed(tracing.load_spans()):
            if s.get("trace_id") == trace_id and s.get("stage") == "evaluation":
                return s
        time.sleep(1.0)
    return None


def hw10_stack(log_dir: Path, with_evaluator: bool = True, trace: bool = True) -> AgentStack:
    """Planner, Writer, Reviewer (and the evaluator) as subprocesses with HW10 tracing."""

    os.environ.update({"HW10_TRACE": "1" if trace else "0", "HW10_SPAN_FILE": str(tracing.span_file())})
    agents = ("planner", "writer", "reviewer") + (("evaluator",) if with_evaluator else ())
    return AgentStack(log_dir, agents=agents, extra_env={**HW10_ENV, "HW10_TRACE": "1" if trace else "0"})


def uncached(qa: Any, questions: list[str]) -> list[tuple[str, float | None]]:
    """(question, best cached similarity) for the questions the cache would NOT answer right now."""

    out = []
    for q in questions:
        best = qa.cache.nearest(qa.embedder.embed(q))
        sim = best["similarity"] if best else None
        if sim is None or sim < qa.threshold:
            out.append((q, sim))
    return out
