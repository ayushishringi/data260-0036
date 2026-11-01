"""Shared Kafka configuration, clients and logging for HW8 (s0036)."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from confluent_kafka import Consumer, KafkaError, Producer
from confluent_kafka.admin import AdminClient

SID4 = "0036"
PREFIX = f"s{SID4}"
PORT_BASE = 8000 + int(SID4) % 900
SEED = int(SID4)
VERIFY_SEED = 260000 + int(SID4)
BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")

# Part 1: request/response service for the primary entity (VulnerabilityReport -> "report").
REQUEST_TOPIC = f"{PREFIX}_report_requests"
RESPONSE_TOPIC = f"{PREFIX}_report_responses"
# Part 2/3: three-agent pipeline.
INBOX_TOPIC = f"{PREFIX}_inbox"
TASKS_TOPIC = f"{PREFIX}_tasks"
DRAFTS_TOPIC = f"{PREFIX}_drafts"
FINAL_TOPIC = f"{PREFIX}_final"
DEAD_LETTER_TOPIC = f"{PREFIX}_dead_letter"

TOPIC_PARTITIONS = {
    REQUEST_TOPIC: 1, RESPONSE_TOPIC: 1,
    INBOX_TOPIC: 1, TASKS_TOPIC: 2, DRAFTS_TOPIC: 1, FINAL_TOPIC: 1, DEAD_LETTER_TOPIC: 1,
}

LOG_DIR = Path(os.getenv("HW8_LOG_DIR", Path(__file__).resolve().parents[1] / "reports" / "hw08" / "logs"))


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def log(component: str, event: str, **fields: Any) -> dict[str, Any]:
    """Print one structured log line (and append it to logs/<component>.jsonl)."""

    record = {"ts": now_iso(), "component": component, "event": event, **fields}
    detail = " ".join(f"{k}={json.dumps(v, default=str)}" for k, v in fields.items())
    print(f"{record['ts']} [{component}] {event} {detail}", flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / f"{component.split('#')[0]}.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass  # logging must never break message processing
    return record


def make_producer(**overrides: Any) -> Producer:
    config = {"bootstrap.servers": BOOTSTRAP, "acks": "all", "enable.idempotence": True, "linger.ms": 5}
    config.update(overrides)
    return Producer(config)


def make_consumer(group_id: str, *, auto_commit: bool = False, offset_reset: str = "earliest",
                  **overrides: Any) -> Consumer:
    config = {
        "bootstrap.servers": BOOTSTRAP,
        "group.id": group_id,
        "enable.auto.commit": auto_commit,
        "auto.offset.reset": offset_reset,
        "session.timeout.ms": 10000,
        "max.poll.interval.ms": 300000,
    }
    config.update(overrides)
    return Consumer(config)


def produce_json(producer: Producer, topic: str, value: dict[str, Any], key: str | None = None,
                 partition: int | None = None) -> dict[str, Any]:
    """Produce one JSON message and wait for the broker acknowledgement; returns partition/offset."""

    delivered: dict[str, Any] = {}

    def on_delivery(err: KafkaError | None, msg: Any) -> None:
        if err is not None:
            delivered["error"] = str(err)
        else:
            delivered.update(partition=msg.partition(), offset=msg.offset())

    kwargs: dict[str, Any] = {"value": json.dumps(value).encode("utf-8"), "on_delivery": on_delivery}
    if key is not None:
        kwargs["key"] = key.encode("utf-8")
    if partition is not None:
        kwargs["partition"] = partition
    producer.produce(topic, **kwargs)
    producer.flush(10)
    if "error" in delivered:
        raise RuntimeError(f"delivery to {topic} failed: {delivered['error']}")
    return delivered


def decode(msg: Any) -> dict[str, Any]:
    """Parse a Kafka message value as a JSON object; raises ValueError for anything else."""

    payload = json.loads(msg.value().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("message value is not a JSON object")
    return payload


def wait_for_kafka(timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while True:
        try:
            AdminClient({"bootstrap.servers": BOOTSTRAP}).list_topics(timeout=5)
            return
        except Exception as exc:  # broker not up yet
            if time.time() > deadline:
                raise SystemExit(f"Kafka not reachable at {BOOTSTRAP}: {exc}") from exc
            time.sleep(2)


def topic_partitions() -> dict[str, int]:
    metadata = AdminClient({"bootstrap.servers": BOOTSTRAP}).list_topics(timeout=10)
    return {name: len(t.partitions) for name, t in metadata.topics.items() if name.startswith(PREFIX)}


def assign_at_end(consumer: Consumer, topic: str) -> None:
    """Assign every partition of `topic` at its current high watermark (explicit offsets, no rebalance).

    Used by reply readers: anything produced after this call is guaranteed to be seen.
    """

    from confluent_kafka import TopicPartition

    metadata = consumer.list_topics(topic, timeout=10)
    partitions = []
    for partition_id in metadata.topics[topic].partitions:
        _low, high = consumer.get_watermark_offsets(TopicPartition(topic, partition_id), timeout=10)
        partitions.append(TopicPartition(topic, partition_id, high))
    consumer.assign(partitions)


def flush_stdout() -> None:
    sys.stdout.flush()
