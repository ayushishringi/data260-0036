"""HW8 pure-function tests (no Kafka needed): report service, idempotency store, agent handlers."""

from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from pathlib import Path

from src.report_service import CREATE_OPERATION, GET_OPERATION, handle_request, validate_report

VALID = {"package_name": "lodash", "affected_version": "< 4.17.21", "severity": "High",
         "description": "Prototype pollution through crafted object keys.", "submitter_email": "a@b.edu"}


def request(operation: str, data: object, cid: str = "cid-1") -> dict:
    return {"correlation_id": cid, "reply_to": "s0036_report_responses", "operation": operation, "data": data}


class ReportServiceTests(unittest.TestCase):
    def test_create_then_get_round_trip(self) -> None:
        store: dict = {}
        created = handle_request(request(CREATE_OPERATION, VALID, "c1"), store)
        self.assertTrue(created["success"])
        self.assertEqual(created["correlation_id"], "c1")
        uuid.UUID(created["report_id"])  # a real UUID
        fetched = handle_request(request(GET_OPERATION, {"report_id": created["report_id"]}, "c2"), store)
        self.assertEqual(fetched["report"]["package_name"], "lodash")
        self.assertEqual(fetched["report"]["severity"], "high")
        self.assertEqual(fetched["correlation_id"], "c2")

    def test_errors_keep_correlation_id(self) -> None:
        store: dict = {}
        cases = [
            (request(GET_OPERATION, {"report_id": "missing"}, "x1"), "Report not found"),
            (request("DELETE_REPORT", {}, "x2"), "Unknown operation"),
            ({"correlation_id": "x3", "operation": GET_OPERATION}, "Malformed request"),
        ]
        for message, error in cases:
            response = handle_request(message, store)
            self.assertFalse(response["success"])
            self.assertIn(error, response["error"])
            self.assertEqual(response["correlation_id"], message["correlation_id"])

    def test_validation_rejects_missing_empty_and_invalid(self) -> None:
        for data, fragment in [
            ({k: v for k, v in VALID.items() if k != "severity"}, "Missing"),
            ({**VALID, "package_name": "  "}, "non-empty"),
            ({**VALID, "severity": "urgent"}, "severity"),
            ({**VALID, "submitter_email": "not-an-email"}, "email"),
            ({**VALID, "description": "short"}, "description"),
            ({**VALID, "extra": "x"}, "Unknown field"),
            ("not an object", "JSON object"),
        ]:
            clean, error = validate_report(data)
            self.assertIsNone(clean)
            self.assertIn(fragment, error)


class PipelineTests(unittest.TestCase):
    def test_processed_store_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["HW8_STATE_DIR"] = tmp
            import importlib

            import src.agent_pipeline as pipeline
            importlib.reload(pipeline)
            pipeline.ProcessedStore("g").mark("cid-9")
            self.assertTrue(pipeline.ProcessedStore("g").seen("cid-9"))
            self.assertTrue(Path(tmp, "g.json").exists())

    def test_writer_rejects_poison_and_reviewer_approves_good_draft(self) -> None:
        from src.agent_pipeline import PoisonMessage, reviewer_handle, writer_handle
        os.environ["HW8_LLM"] = "0"
        with self.assertRaises(PoisonMessage):
            writer_handle({"correlation_id": "p", "kind": "task", "question": "q", "plan": "not-a-list"})
        draft = writer_handle({"correlation_id": "g", "kind": "task", "question": "Why pin dependency versions?",
                               "plan": ["Explain pinning dependency versions", "Give one example", "List fixes"]})
        final = reviewer_handle(draft)
        self.assertEqual(final["correlation_id"], "g")
        self.assertIn(final["status"], ("approved", "needs_revision"))

    def test_ordering_messages_are_deterministic(self) -> None:
        import scripts.run_hw8_failures as runner
        first, second = runner.ordering_messages(), runner.ordering_messages()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 20)
        for entity in runner.ENTITIES:
            seqs = [m["seq"] for m in first if m["entity"] == entity]
            self.assertEqual(seqs, list(range(1, len(seqs) + 1)))


if __name__ == "__main__":
    unittest.main()
