"""HW8 Parts 2-3: Planner -> Writer -> Reviewer over Kafka, with the failure-handling fixes.

Each agent is a separate process (planner.py, writer.py, reviewer.py) built on run_agent() below.
No agent calls another: they only read one topic and write the next.

Failure handling (each switch reproduces the "before fix" behavior for Part 3):
  HW8_IDEMPOTENT=1   skip a correlation_id this agent already completed (persisted on disk)   [0 = off]
  HW8_COMMIT=after   commit the offset only after the output is acknowledged by Kafka        [before = commit on receipt]
  HW8_RETRY=bounded  retry HW8_MAX_RETRIES times, then move the message to s0036_dead_letter  [unbounded = retry forever]
Other knobs: HW8_LLM (1 = use the local model, 0 = deterministic template), HW8_SLOW_SECONDS (simulated long work),
HW8_GROUP_SUFFIX (separate consumer groups per experiment), HW8_INSTANCE (name of this process in the logs).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from confluent_kafka import TopicPartition

from src.kafka_common import (
    DEAD_LETTER_TOPIC,
    DRAFTS_TOPIC,
    FINAL_TOPIC,
    INBOX_TOPIC,
    PREFIX,
    TASKS_TOPIC,
    decode,
    log,
    make_consumer,
    make_producer,
    now_iso,
    produce_json,
    wait_for_kafka,
)

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.getenv("HW8_STATE_DIR", ROOT / ".hw8_state"))


class PoisonMessage(Exception):
    """A message this agent can never process (bad JSON or invalid fields)."""


def env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


# ----------------------------------------------------------------------------- idempotency


class ProcessedStore:
    """correlation_ids an agent has fully completed, persisted so a restart remembers them."""

    def __init__(self, group: str) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.path = STATE_DIR / f"{group}.json"
        self.done: set[str] = set(json.loads(self.path.read_text())) if self.path.exists() else set()

    def seen(self, correlation_id: str) -> bool:
        return correlation_id in self.done

    def mark(self, correlation_id: str) -> None:
        self.done.add(correlation_id)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(self.done)))
        tmp.replace(self.path)  # atomic, so a crash never leaves a half-written file


# ----------------------------------------------------------------------------- the agent runtime


def run_agent(name: str, in_topic: str, out_topic: str | None,
              handle: Callable[[dict[str, Any]], dict[str, Any] | None]) -> None:
    """Consume in_topic, call handle(message), produce its result to out_topic, then commit."""

    wait_for_kafka()
    instance = env("HW8_INSTANCE", name)
    group = f"{PREFIX}_{name}s{env('HW8_GROUP_SUFFIX', '')}"
    idempotent = env("HW8_IDEMPOTENT", "1") == "1"
    commit_mode = env("HW8_COMMIT", "after")
    retry_mode = env("HW8_RETRY", "bounded")
    max_retries = int(env("HW8_MAX_RETRIES", "3"))
    slow_seconds = float(env("HW8_SLOW_SECONDS", "0"))
    component = f"{name}#{instance}" if instance != name else name
    store = ProcessedStore(group) if idempotent else None
    consumer = make_consumer(group)
    producer = make_producer()

    def on_assign(c: Any, partitions: list[TopicPartition]) -> None:
        # A brand-new group starts at the current end of the topic (so old experiments are not
        # replayed); a group that has committed offsets resumes exactly where it committed.
        committed = c.committed(partitions, timeout=10)
        start = []
        for tp in committed:
            if tp.offset < 0:
                _low, high = c.get_watermark_offsets(TopicPartition(tp.topic, tp.partition), timeout=10)
                start.append(TopicPartition(tp.topic, tp.partition, high))
            else:
                start.append(tp)
        c.assign(start)
        c.commit(offsets=start, asynchronous=False)  # record the starting point for a new group
        log(component, "Consumer is ready and listening...", topic=in_topic, group=group,
            partitions={tp.partition: tp.offset for tp in start}, idempotent=idempotent, commit=commit_mode,
            retry=retry_mode, max_retries=max_retries)

    consumer.subscribe([in_topic], on_assign=on_assign)
    running = True

    def stop(*_args: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while running:
        msg = consumer.poll(1.0)
        if msg is None or msg.error():
            continue
        where = {"partition": msg.partition(), "offset": msg.offset()}
        if commit_mode == "before":  # BEFORE FIX: offset committed as soon as the message is read
            consumer.commit(message=msg, asynchronous=False)
            log(component, "COMMITTED offset on receipt (before processing)", **where)

        attempt = 0
        while True:
            attempt += 1
            try:
                message = decode(msg)
            except (ValueError, UnicodeDecodeError) as exc:
                message, error = None, PoisonMessage(f"not valid JSON: {exc}")
            else:
                error = None
            cid = message.get("correlation_id") if isinstance(message, dict) else None
            try:
                if error:
                    raise error
                if attempt == 1:
                    log(component, "RECEIVED", topic=in_topic, correlation_id=cid, **where,
                        kind=message.get("kind", "question"))
                if store is not None and cid and store.seen(cid):
                    log(component, "DUPLICATE skipped (already processed)", correlation_id=cid, **where)
                    output = None
                    break
                if slow_seconds:
                    log(component, "STARTED long processing", correlation_id=cid, seconds=slow_seconds, **where)
                    time.sleep(slow_seconds)
                output = handle(message)
                if output is not None and out_topic:
                    log(component, "SENT", topic=out_topic, correlation_id=cid,
                        **{k: v for k, v in output.items() if k in ("plan", "draft", "status", "answer")})
                    produce_json(producer, out_topic, output, key=output.get("correlation_id"))
                if store is not None and cid:
                    store.mark(cid)
                break
            except Exception as exc:  # poison or transient failure
                log(component, "PROCESSING FAILED", correlation_id=cid, attempt=attempt, error=str(exc), **where)
                if retry_mode == "unbounded":  # BEFORE FIX: retry forever, blocking the partition
                    time.sleep(1.0)
                    continue
                if attempt < max_retries:
                    time.sleep(0.5 * attempt)
                    continue
                dead = {"correlation_id": cid, "failed_agent": name, "source_topic": in_topic, **where,
                        "attempts": attempt, "error": str(exc), "ts": now_iso(),
                        "original": message if message is not None else msg.value().decode("utf-8", "replace")}
                produce_json(producer, DEAD_LETTER_TOPIC, dead, key=cid)
                log(component, "MOVED to dead-letter topic", topic=DEAD_LETTER_TOPIC, correlation_id=cid,
                    attempts=attempt, **where)
                break
        if commit_mode == "after":  # AFTER FIX: commit only once the output is safely in Kafka
            consumer.commit(message=msg, asynchronous=False)
            log(component, "COMMITTED offset after processing", correlation_id=cid, **where)
    consumer.close()


# ----------------------------------------------------------------------------- the three agents


def use_llm() -> bool:
    return env("HW8_LLM", "1") == "1"


def ask_model(system: str, user: str) -> str:
    from src.model_client import ModelClient
    result = ModelClient().complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                    temperature=0.2, think=True)
    return result.text.strip()


def planner_handle(message: dict[str, Any]) -> dict[str, Any]:
    question = message.get("question")
    if not isinstance(question, str) or not question.strip():
        raise PoisonMessage("question must be a non-empty string")
    if use_llm():
        text = ask_model("You plan answers about open-source package vulnerabilities. Reply with exactly 3 short "
                         "numbered steps a writer should follow. No other text.", question)
        plan = [re.sub(r"^\s*\d+[.)]\s*", "", line).strip() for line in text.splitlines() if line.strip()][:3]
    else:
        plan = [f"Define the key terms in: {question}", "Explain the main risk with one concrete example",
                "Give two practical mitigation steps"]
    return {"correlation_id": message["correlation_id"], "kind": "task", "question": question, "plan": plan,
            "planned_at": now_iso()}


def writer_handle(message: dict[str, Any]) -> dict[str, Any] | None:
    if message.get("kind") == "ordering_probe":
        # Part 3 ordering test: simulated work whose duration is fixed per message (seeded).
        seed = int(hashlib.sha256(message["probe_id"].encode()).hexdigest(), 16) % 10_000
        time.sleep(random.Random(seed).uniform(0.05, 0.6))
        log(f"writer#{env('HW8_INSTANCE', 'writer')}", "PROCESSED ordering probe",
            probe_id=message["probe_id"], entity=message["entity"], seq=message["seq"], sent_index=message["index"])
        return None
    plan, question = message.get("plan"), message.get("question")
    if not isinstance(plan, list) or not plan or not all(isinstance(step, str) for step in plan):
        raise PoisonMessage("plan must be a non-empty list of strings")
    if not isinstance(question, str):
        raise PoisonMessage("question must be a string")
    if use_llm():
        draft = ask_model("You write concise, accurate answers (120-180 words) about open-source package "
                          "vulnerabilities. Follow the plan.",
                          f"Question: {question}\nPlan:\n" + "\n".join(f"- {s}" for s in plan))
    else:
        draft = f"Answer to '{question}': " + " ".join(f"({i}) {step}." for i, step in enumerate(plan, 1))
    return {"correlation_id": message["correlation_id"], "kind": "draft", "question": question, "plan": plan,
            "draft": draft, "written_at": now_iso()}


def reviewer_handle(message: dict[str, Any]) -> dict[str, Any]:
    draft, question = message.get("draft"), message.get("question")
    if not isinstance(draft, str) or not isinstance(question, str):
        raise PoisonMessage("draft and question must be strings")
    words = len(draft.split())
    keywords = {w for w in re.findall(r"[a-z]{5,}", question.lower())}
    covered = sum(1 for w in keywords if w in draft.lower())
    checks = {"non_empty": words > 0, "length_ok": 15 <= words <= 400,
              "on_topic": covered >= max(1, len(keywords) // 3)}
    status = "approved" if all(checks.values()) else "needs_revision"
    return {"correlation_id": message["correlation_id"], "status": status, "answer": draft, "question": question,
            "review": {"checks": checks, "words": words}, "reviewed_at": now_iso()}


AGENTS = {
    "planner": (INBOX_TOPIC, TASKS_TOPIC, planner_handle),
    "writer": (TASKS_TOPIC, DRAFTS_TOPIC, writer_handle),
    "reviewer": (DRAFTS_TOPIC, FINAL_TOPIC, reviewer_handle),
}


def main(name: str) -> None:
    in_topic, out_topic, handle = AGENTS[name]
    run_agent(name, in_topic, out_topic, handle)
