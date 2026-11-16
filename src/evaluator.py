"""HW10 Part 2: evaluator agent for the s0036 Planner -> Writer -> Reviewer pipeline.

A separate Kafka consumer (evaluator.py) reads s0036_tasks (plan), s0036_drafts (draft), s0036_final
(final answer) and s0036_dead_letter, joins them on correlation_id (= trace_id), and once all three
are present scores them with DeepEval GEval on the local judge (src/judge.py):

  plan_quality        plan vs question                       -> score + reason
  writer_helpfulness  draft vs question + advisory facts      -> score + trace_id
  final_helpfulness   final answer vs question                -> score + final answer
  final_vs_draft      draft scored with the final criterion   -> both scores, difference, interpretation

Every record keeps the original messages (and their topic/partition/offset/timestamp) so the
evaluation can be reproduced. Bounds: malformed messages are logged and skipped; a join that is still
incomplete after HW10_EVAL_JOIN_TIMEOUT seconds is closed as "incomplete"; each judge call has its own
timeout (HW10_JUDGE_TIMEOUT) and the whole evaluation a budget (HW10_EVAL_BUDGET); an unreachable judge
fails fast. The result is an `evaluation` span on the same trace and one line in evaluations.jsonl.
"""

from __future__ import annotations

import json
import os
import signal
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src import tracing
from src.kafka_common import (
    DEAD_LETTER_TOPIC,
    DRAFTS_TOPIC,
    FINAL_TOPIC,
    PREFIX,
    TASKS_TOPIC,
    log,
    make_consumer,
    now_iso,
    wait_for_kafka,
)

ROOT = Path(__file__).resolve().parents[1]
EVAL_FILE = Path(os.getenv("HW10_EVAL_FILE", ROOT / "reports" / "hw10" / "raw" / "evaluations.jsonl"))
ROLE = {TASKS_TOPIC: "plan", DRAFTS_TOPIC: "draft", FINAL_TOPIC: "final", DEAD_LETTER_TOPIC: "dead"}
COMPONENT = "evaluator"

JudgeFn = Callable[..., dict[str, Any]]


def interpret(draft_score: float | None, final_score: float | None, same_text: bool, status: str | None) -> str:
    """Plain-language reading of the final-vs-draft comparison (no forced positive conclusion)."""

    if draft_score is None or final_score is None:
        return "Not compared: the judge did not return both scores."
    diff = round(final_score - draft_score, 2)
    if same_text:
        reason = (f"the Reviewer {status or 'returned'} the draft without rewriting it (final text identical to "
                  "the draft); it only runs rule checks (length, on-topic) and cannot add content.")
        if diff == 0:
            return f"No improvement: {reason[0].upper()}{reason[1:]} Both versions got the same score."
        return (f"No real improvement: {reason[0].upper()}{reason[1:]} The {diff:+.2f} difference is judge "
                "variance on identical text, not a quality change.")
    if diff > 0:
        return f"Improved by {diff:+.2f}: the Reviewer's edits made the final answer more helpful than the draft."
    if diff < 0:
        return f"Regressed by {diff:+.2f}: the final answer scored lower than the draft the Writer produced."
    return "Unchanged: the final text differs from the draft but the judge scored both the same."


class Evaluator:
    """Join buffer + scoring. Kafka-free so tests can drive it directly."""

    def __init__(self, judge_fn: JudgeFn | None = None, join_timeout: float | None = None,
                 budget: float | None = None, sink: Path | None = None,
                 available: Callable[[], bool] | None = None) -> None:
        if judge_fn is None or available is None:
            from src import judge
            judge_fn = judge_fn or judge.evaluate
            available = available or judge.judge_ollama_available
        self.judge_fn, self.available = judge_fn, available
        self.join_timeout = join_timeout if join_timeout is not None else float(
            os.getenv("HW10_EVAL_JOIN_TIMEOUT", "600"))
        self.budget = budget if budget is not None else float(os.getenv("HW10_EVAL_BUDGET", "900"))
        self.sink = sink or EVAL_FILE
        self.pending: dict[str, dict[str, Any]] = {}

    # -- joining
    def on_message(self, topic: str, payload: Any, meta: dict[str, Any]) -> dict[str, Any] | None:
        """Add one message to its join; returns the finished record when this message completes it."""

        role = ROLE.get(topic)
        if role is None:
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("correlation_id"), str):
            log(COMPONENT, "MALFORMED message skipped (no correlation_id)", topic=topic, **meta)
            return None
        cid = payload["correlation_id"]
        entry = self.pending.setdefault(cid, {"first_seen": time.time()})
        entry[role] = {**payload, "_kafka": {"topic": topic, **meta}}
        if role == "dead":
            return self.finish(cid, "not_evaluated")
        if all(r in entry for r in ("plan", "draft", "final")):
            return self.finish(cid, "evaluated")
        return None

    def expire(self, now: float | None = None) -> list[dict[str, Any]]:
        """Close joins that waited longer than join_timeout (a lost or never-sent message)."""

        now = time.time() if now is None else now
        late = [cid for cid, e in self.pending.items() if now - e["first_seen"] > self.join_timeout]
        return [self.finish(cid, "incomplete") for cid in late]

    # -- scoring
    def finish(self, cid: str, outcome: str) -> dict[str, Any]:
        entry = self.pending.pop(cid)
        start = time.time()
        messages = {r: entry[r] for r in ("plan", "draft", "final", "dead") if r in entry}
        question = next((m.get("question") for m in messages.values() if isinstance(m.get("question"), str)), None)
        record: dict[str, Any] = {"trace_id": cid, "correlation_id": cid, "question": question,
                                  "outcome": outcome, "evaluated_at": now_iso(), "messages": messages}
        error = None
        if outcome == "not_evaluated":
            dead = entry["dead"]
            error = (f"upstream failure: {dead.get('failed_agent')} moved the message to {DEAD_LETTER_TOPIC} "
                     f"after {dead.get('attempts')} attempts: {dead.get('error')}")
        elif outcome == "incomplete":
            missing = [r for r in ("plan", "draft", "final") if r not in entry]
            error = f"join timed out after {self.join_timeout:.0f}s; missing {', '.join(missing)}"
        else:
            record.update(self.score(messages, question or ""))
            failed = [k for k in ("plan_quality", "writer_helpfulness", "final_helpfulness")
                      if record[k]["status"] != "ok"]
            if record["final_vs_draft"]["draft_status"] != "ok":
                failed.append("draft_score")
            if failed:
                error = "judge errors: " + "; ".join(
                    f"{k}={record.get(k, {}).get('error') or record['final_vs_draft'].get('draft_error')}"
                    for k in failed)
        end = time.time()
        record.update(status="error" if error else "ok", error=error, evaluation_ms=round((end - start) * 1000, 1))
        tracing.write_span(cid, "evaluation", start, end, record["status"], error, COMPONENT, outcome=outcome,
                           scores={k: record[k]["score"] for k in ("plan_quality", "writer_helpfulness",
                                                                   "final_helpfulness") if k in record},
                           failed_stage=(entry.get("dead") or {}).get("failed_agent"))
        self.save(record)
        log(COMPONENT, "EVALUATED" if outcome == "evaluated" else f"NOT EVALUATED ({outcome})", correlation_id=cid,
            status=record["status"], error=error,
            **{k: record[k]["score"] for k in ("plan_quality", "writer_helpfulness", "final_helpfulness")
               if k in record})
        return record

    def score(self, messages: dict[str, Any], question: str) -> dict[str, Any]:
        plan_msg, draft_msg, final_msg = messages["plan"], messages["draft"], messages["final"]
        plan = plan_msg.get("plan")
        plan_text = "\n".join(f"{n}. {s}" for n, s in enumerate(plan, 1)) if isinstance(plan, list) else ""
        draft = draft_msg.get("draft") if isinstance(draft_msg.get("draft"), str) else ""
        final = final_msg.get("answer") if isinstance(final_msg.get("answer"), str) else ""
        facts = [f for f in draft_msg.get("facts") or [] if isinstance(f, str)]
        deadline = time.time() + self.budget
        up = self.available()

        def run(key: str, output: str, context: list[str] | None = None) -> dict[str, Any]:
            left = deadline - time.time()
            if not up:
                return {"score": None, "reason": None, "status": "error", "error": "judge unavailable", "judge_ms": 0}
            if left <= 0:
                return {"score": None, "reason": None, "status": "error",
                        "error": f"evaluation budget of {self.budget:.0f}s used up", "judge_ms": 0}
            return self.judge_fn(key, question, output, context, timeout=left)

        plan_r = run("plan_quality", plan_text)
        writer_r = run("writer_helpfulness", draft, facts)
        final_r = run("final_helpfulness", final)
        draft_r = run("final_helpfulness", draft)
        same = draft.strip() == final.strip()
        ds, fs = draft_r["score"], final_r["score"]
        return {
            "plan_quality": {**plan_r, "plan": plan},
            "writer_helpfulness": {**writer_r, "trace_id": draft_msg.get("correlation_id"),
                                   "grounding_facts": facts},
            "final_helpfulness": {**final_r, "final_answer": final, "review_status": final_msg.get("status")},
            "final_vs_draft": {"draft_score": ds, "final_score": fs,
                               "difference": None if ds is None or fs is None else round(fs - ds, 2),
                               "draft_equals_final": same, "draft_reason": draft_r["reason"],
                               "draft_status": draft_r["status"], "draft_error": draft_r["error"],
                               "interpretation": interpret(ds, fs, same, final_msg.get("status"))},
        }

    def save(self, record: dict[str, Any]) -> None:
        from src.judge import JUDGE_SETTINGS
        record.setdefault("judge", JUDGE_SETTINGS)
        self.sink.parent.mkdir(parents=True, exist_ok=True)
        with self.sink.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, default=str) + "\n")


def run_evaluator() -> None:
    """Kafka loop: subscribe to tasks/drafts/final/dead_letter from their current end and evaluate joins."""

    from confluent_kafka import TopicPartition

    from src.agent_pipeline import trace_queue_wait
    from src.kafka_common import decode

    wait_for_kafka()
    group = f"{PREFIX}_evaluators{os.getenv('HW8_GROUP_SUFFIX', '')}_{uuid.uuid4().hex[:6]}"
    topics = [TASKS_TOPIC, DRAFTS_TOPIC, FINAL_TOPIC, DEAD_LETTER_TOPIC]
    # Auto-commit: an evaluation is a side measurement, so at-most-once is acceptable; long judge calls
    # must not trigger a rebalance, hence the larger max.poll.interval.ms.
    consumer = make_consumer(group, auto_commit=True, offset_reset="latest", **{"max.poll.interval.ms": 1800000})
    evaluator = Evaluator()

    def on_assign(c: Any, partitions: list[TopicPartition]) -> None:
        start = []
        for tp in partitions:
            _low, high = c.get_watermark_offsets(TopicPartition(tp.topic, tp.partition), timeout=10)
            start.append(TopicPartition(tp.topic, tp.partition, high))
        c.assign(start)
        log(COMPONENT, "Consumer is ready and listening...", topics=topics, group=group,
            join_timeout_s=evaluator.join_timeout, budget_s=evaluator.budget, eval_file=str(evaluator.sink))

    consumer.subscribe(topics, on_assign=on_assign)
    running = True

    def stop(*_args: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        msg = consumer.poll(1.0)
        evaluator.expire()
        if msg is None or msg.error():
            continue
        received_at = time.time()
        meta = {"partition": msg.partition(), "offset": msg.offset(), "kafka_timestamp_ms": msg.timestamp()[1]}
        try:
            payload = decode(msg)
        except (ValueError, UnicodeDecodeError) as exc:
            log(COMPONENT, "MALFORMED message skipped", topic=msg.topic(), error=str(exc), **meta)
            continue
        if msg.topic() == FINAL_TOPIC:
            trace_queue_wait(payload.get("correlation_id"), FINAL_TOPIC, msg, received_at, COMPONENT)
        evaluator.on_message(msg.topic(), payload, meta)
    consumer.close()
