"""HW8 Part 1 worker: consume s0036_report_requests, process, reply to the topic named by reply_to."""

from __future__ import annotations

import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.kafka_common import (  # noqa: E402
    REQUEST_TOPIC,
    decode,
    log,
    make_consumer,
    make_producer,
    produce_json,
    wait_for_kafka,
)
from src.report_service import handle_request  # noqa: E402

COMPONENT = "worker"


def main() -> None:
    wait_for_kafka()
    store: dict[str, dict] = {}  # plain in-memory dictionary, as required for this exercise
    consumer = make_consumer("s0036_report_workers")
    producer = make_producer()
    announced = False

    def on_assign(_consumer: object, partitions: list) -> None:
        nonlocal announced
        if not announced:  # logged from the rebalance callback, so no message is polled and dropped first
            log(COMPONENT, "Consumer is ready and listening...", topic=REQUEST_TOPIC,
                partitions=[p.partition for p in partitions])
            announced = True

    consumer.subscribe([REQUEST_TOPIC], on_assign=on_assign)

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
        try:
            request = decode(msg)
        except ValueError as exc:
            log(COMPONENT, "DROPPED unparseable request", offset=msg.offset(), error=str(exc))
            consumer.commit(message=msg, asynchronous=False)
            continue
        cid = request.get("correlation_id")
        log(COMPONENT, "RECEIVED request", topic=msg.topic(), partition=msg.partition(), offset=msg.offset(),
            correlation_id=cid, operation=request.get("operation"), data=request.get("data"))
        response = handle_request(request, store)
        log(COMPONENT, "PROCESSED request", correlation_id=cid, success=response["success"],
            result=response.get("report_id") or response.get("error") or "report returned")
        reply_to = request.get("reply_to") if isinstance(request.get("reply_to"), str) else None
        if reply_to:
            log(COMPONENT, "SENT response", topic=reply_to, correlation_id=cid, response=response)
            sent = produce_json(producer, reply_to, response, key=cid)
            log(COMPONENT, "response acknowledged by broker", topic=reply_to, correlation_id=cid, **sent)
        else:
            log(COMPONENT, "NO reply_to; response not sent", correlation_id=cid)
        consumer.commit(message=msg, asynchronous=False)  # commit only after the reply is acknowledged
    consumer.close()


if __name__ == "__main__":
    main()
