"""HW8 Part 2: send a question to s0036_inbox and wait for the matching message on s0036_final.

Usage:
  python send_question.py "How should a team respond to a critical CVE in a transitive dependency?"
  python send_question.py --replay          # resend the last question with the SAME correlation_id
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.agent_pipeline import STATE_DIR  # noqa: E402
from src.kafka_common import (  # noqa: E402
    FINAL_TOPIC,
    INBOX_TOPIC,
    assign_at_end,
    decode,
    log,
    make_consumer,
    make_producer,
    now_iso,
    produce_json,
)

LAST = STATE_DIR / "last_question.json"
DEFAULT_QUESTION = "How should a team respond to a critical CVE found in a transitive dependency?"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--replay", action="store_true", help="resend the last message unchanged")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--no-wait", action="store_true")
    args = parser.parse_args()

    if args.replay:
        message = json.loads(LAST.read_text())
        log("sender", "REPLAYING previous message with the same correlation_id",
            correlation_id=message["correlation_id"])
    else:
        message = {"correlation_id": str(uuid.uuid4()), "kind": "question", "question": args.question,
                   "asked_at": now_iso()}
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAST.write_text(json.dumps(message))

    reader = make_consumer(f"s0036_final_reader_{uuid.uuid4().hex[:8]}", offset_reset="latest")
    assign_at_end(reader, FINAL_TOPIC)  # read everything produced to s0036_final from now on
    log("sender", "SENT question", topic=INBOX_TOPIC, correlation_id=message["correlation_id"],
        question=message["question"])
    produce_json(make_producer(), INBOX_TOPIC, message, key=message["correlation_id"])
    if args.no_wait:
        return
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        msg = reader.poll(1.0)
        if msg is None or msg.error():
            continue
        final = decode(msg)
        if final.get("correlation_id") == message["correlation_id"]:
            log("sender", "RECEIVED final", topic=FINAL_TOPIC, correlation_id=final["correlation_id"],
                partition=msg.partition(), offset=msg.offset(), status=final.get("status"))
            print(json.dumps(final, indent=2))
            return
    log("sender", "NO final message before timeout (expected after a replay with idempotency on)",
        correlation_id=message["correlation_id"], timeout_s=args.timeout)


if __name__ == "__main__":
    main()
