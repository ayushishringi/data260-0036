"""Kafka request/response client for the HW8 report service.

The caller creates correlation_id once; this client sends it unchanged in the request and returns
only the response that echoes the same value. A background thread reads s0036_report_responses
from its current end and hands each response to the waiting caller.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from src.kafka_common import (
    REQUEST_TOPIC,
    RESPONSE_TOPIC,
    assign_at_end,
    decode,
    log,
    make_consumer,
    make_producer,
    produce_json,
)


class ReportRpcClient:
    """Thread-safe request/response client; one instance can serve many concurrent callers."""

    def __init__(self, component: str = "client") -> None:
        self.component = component
        self.producer = make_producer()
        self.consumer = make_consumer(f"s0036_reply_reader_{uuid.uuid4().hex[:8]}", offset_reset="latest")
        assign_at_end(self.consumer, RESPONSE_TOPIC)
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._read_replies, daemon=True)
        self._thread.start()

    def _read_replies(self) -> None:
        while self._running:
            msg = self.consumer.poll(0.5)
            if msg is None or msg.error():
                continue
            try:
                response = decode(msg)
            except ValueError:
                continue
            cid = response.get("correlation_id")
            with self._lock:
                slot = self._pending.get(cid)
            if slot is not None:  # responses for other callers are ignored
                slot["response"] = response
                slot["meta"] = {"partition": msg.partition(), "offset": msg.offset()}
                slot["event"].set()

    @staticmethod
    def new_correlation_id() -> str:
        return str(uuid.uuid4())

    def request(self, operation: str, data: Any, correlation_id: str | None = None,
                timeout: float = 15.0) -> dict[str, Any]:
        """Send one request and wait for the response with the same correlation_id."""

        cid = correlation_id or self.new_correlation_id()
        message = {"correlation_id": cid, "reply_to": RESPONSE_TOPIC, "operation": operation, "data": data}
        slot: dict[str, Any] = {"event": threading.Event()}
        with self._lock:
            self._pending[cid] = slot
        try:
            log(self.component, "SENT request", topic=REQUEST_TOPIC, correlation_id=cid, message=message)
            sent = produce_json(self.producer, REQUEST_TOPIC, message, key=cid)
            log(self.component, "request acknowledged by broker", topic=REQUEST_TOPIC, correlation_id=cid, **sent)
            if not slot["event"].wait(timeout):
                log(self.component, "TIMEOUT waiting for response", correlation_id=cid, timeout_s=timeout)
                return {"correlation_id": cid, "success": False, "error": "Timed out waiting for worker"}
            response = slot["response"]
            log(self.component, "RECEIVED response", topic=RESPONSE_TOPIC, correlation_id=cid,
                correlation_id_preserved=response.get("correlation_id") == cid, response=response, **slot["meta"])
            return response
        finally:
            with self._lock:
                self._pending.pop(cid, None)

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=2)
        self.consumer.close()
