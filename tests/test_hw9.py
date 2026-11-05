"""HW9 pure-function tests (no Redis, Kafka or model needed): counter, cache handler, evaluator, lessons."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

import numpy as np
from sqlalchemy import create_engine, text

from src import advisory_lookup
from src.redis_store import ReportCache, views_key
from src.self_improving import EvaluatorAgent, LessonStore, SelfImprovingSystem, asked_fields, lesson_for
from src.semantic_cache import CachedQA

ROOT = Path(__file__).resolve().parents[1]


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    def delete(self, key: str) -> int:
        return int(self.data.pop(key, None) is not None)


class CounterTests(unittest.TestCase):
    def test_incr_every_view_and_sync_every_ten(self) -> None:
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE vulnerability_reports (id INTEGER PRIMARY KEY, view_count INTEGER)"))
            conn.execute(text("INSERT INTO vulnerability_reports VALUES (7, 0)"))
        cache = ReportCache(FakeRedis(), engine)
        with self.assertLogs("s0036.hw9", level="INFO") as logs:
            counts = [cache.increment_report_views(7) for _ in range(25)]
        self.assertEqual(counts, list(range(1, 26)))
        self.assertEqual(cache.database_view_count(7), 20)
        self.assertEqual(len([m for m in logs.output if "Synced views to database" in m]), 2)
        self.assertEqual(views_key(7), "s0036:views:report:7")


class LookupTests(unittest.TestCase):
    def test_package_mentions_use_word_boundaries(self) -> None:
        self.assertTrue(advisory_lookup.mentions("Which ws version fixes it?", "ws"))
        self.assertFalse(advisory_lookup.mentions("What is in the news?", "ws"))
        self.assertFalse(advisory_lookup.mentions("How does Dependabot open a pull request?", "requests"))
        self.assertTrue(advisory_lookup.mentions("Is golang.org/x/net affected?", "golang.org/x/net"))

    def test_data_version_changes_with_content(self) -> None:
        row = {"id": 1, "affected_version": "< 2.31.0", "severity": "medium", "description": "d",
               "updated_at": "2026-11-04 10:00:00"}
        same = advisory_lookup.data_version([dict(row)])
        self.assertEqual(advisory_lookup.data_version([row]), same)
        self.assertNotEqual(advisory_lookup.data_version([{**row, "severity": "high"}]), same)
        self.assertEqual(advisory_lookup.data_version([]), "none")


class FakeCache:
    def __init__(self) -> None:
        self.entries: dict[str, dict] = {}

    def nearest(self, vector: np.ndarray) -> dict | None:
        best = None
        for key, e in self.entries.items():
            sim = float(np.dot(vector, e["vector"]))
            if best is None or sim > best["similarity"]:
                best = {"key": key, "query": e["query"], "answer": e["answer"], "data_version": e["version"],
                        "record_ids": e["ids"], "similarity": round(sim, 4)}
        return best

    def store(self, query: str, vector: np.ndarray, answer: str, version: str, ids: list[int], **_: str) -> str:
        key = f"k{len(self.entries)}"
        self.entries[key] = {"query": query, "vector": vector, "answer": answer, "version": version, "ids": ids}
        return key

    def delete(self, key: str) -> None:
        self.entries.pop(key, None)


class FakeEmbedder:
    def embed(self, text_: str) -> np.ndarray:
        vector = np.array([text_.lower().count(c) for c in "aeiouxyz"], dtype=np.float32) + 0.01
        return vector / np.linalg.norm(vector)


class FakePipeline:
    def __init__(self) -> None:
        self.calls = 0

    def ask(self, question: str, timeout: float = 300) -> dict:
        self.calls += 1
        return {"correlation_id": f"c{self.calls}", "status": "approved", "answer": f"answer {self.calls}"}


class CachedQATests(unittest.TestCase):
    def setUp(self) -> None:
        self.version = "v-1"
        patches = [mock.patch.object(advisory_lookup, "find_records", return_value=[{"id": 5}]),
                   mock.patch.object(advisory_lookup, "data_version", side_effect=lambda rs: self.version),
                   mock.patch.object(advisory_lookup, "current_version", side_effect=lambda ids: self.version),
                   mock.patch("src.semantic_cache.log")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.pipeline = FakePipeline()
        self.qa = CachedQA(FakeCache(), FakeEmbedder(), self.pipeline, threshold=0.85)

    def test_miss_then_exact_hit(self) -> None:
        first = self.qa.ask("Which lodash version fixes it?")
        second = self.qa.ask("Which lodash version fixes it?")
        self.assertFalse(first["is_cached"])
        self.assertTrue(second["is_cached"])
        self.assertEqual(second["similarity"], 1.0)
        self.assertEqual(second["answer"], first["answer"])
        self.assertEqual(self.pipeline.calls, 1)
        self.assertGreaterEqual(second["latency_ms"], 0)

    def test_version_change_invalidates(self) -> None:
        self.qa.ask("Which lodash version fixes it?")
        self.version = "v-2"  # the record changed
        stale = CachedQA(self.qa.cache, self.qa.embedder, self.pipeline, invalidation="none").ask(
            "Which lodash version fixes it?")
        self.assertTrue(stale["is_cached"])  # without the check the old answer is served
        fresh = self.qa.ask("Which lodash version fixes it?")
        self.assertFalse(fresh["is_cached"])
        self.assertTrue(fresh["stale_invalidated"])
        self.assertEqual(fresh["answer"], "answer 2")

    def test_store_on_miss_false_keeps_cache_unchanged(self) -> None:
        qa = CachedQA(FakeCache(), FakeEmbedder(), self.pipeline, store_on_miss=False)
        qa.ask("q one")
        self.assertEqual(qa.cache.entries, {})


class SweepScoreTests(unittest.TestCase):
    def test_false_hit_definition(self) -> None:
        spec = importlib.util.spec_from_file_location("sweep", ROOT / "scripts" / "run_hw9_sweep.py")
        sweep = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sweep)
        seeds = {"S01": "seed one", "S02": "seed two"}
        hit = {"is_cached": True, "matched_query": "seed one"}
        self.assertEqual(sweep.score({"expected": "hit", "target": "S01"}, hit, seeds), "correct_hit")
        self.assertEqual(sweep.score({"expected": "hit", "target": "S02"}, hit, seeds), "false_hit")
        self.assertEqual(sweep.score({"expected": "miss"}, hit, seeds), "false_hit")
        self.assertEqual(sweep.score({"expected": "hit", "target": "S01"}, {"is_cached": False}, seeds), "missed_hit")


class EvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = EvaluatorAgent()

    def test_fields_and_verdicts(self) -> None:
        self.assertEqual(asked_fields("Which version of lodash fixes CVE-2021-23337?"), ["fixed_version"])
        self.assertEqual(asked_fields("What is the CVE ID for x?"), ["cve"])
        q = "Which version of lodash fixes CVE-2021-23337?"
        self.assertEqual(self.evaluator.evaluate(q, "Upgrade to 4.17.21.")["result"], "PASS")
        wrong = self.evaluator.evaluate(q, "It was fixed in 4.17.20.")
        self.assertEqual((wrong["result"], wrong["failures"][0]["status"]), ("REVISE", "wrong"))
        self.assertIn("4.17.21", wrong["feedback"])
        self.assertEqual(self.evaluator.evaluate(
            "How severe is the axios XSRF-TOKEN disclosure?", "It is rated moderate.")["result"], "PASS")

    def test_unknown_package_must_be_declined(self) -> None:
        q = "What version of fastjsonx fixes its deserialization vulnerability?"
        self.assertEqual(self.evaluator.evaluate(q, "I could not find an advisory record for it.")["result"], "PASS")
        invented = self.evaluator.evaluate(q, "Version 1.2.4 fixes CVE-2022-1234.")
        self.assertEqual(invented["failures"][0]["status"], "unsupported")


class ScriptedAnswering:
    def __init__(self, answers: list[str]) -> None:
        self.answers = answers

    def answer(self, question: str, lessons: list | None = None, **_: object) -> dict:
        return {"answer": self.answers.pop(0), "lessons_used": [x["lesson_id"] for x in lessons or []],
                "looked_up": False, "lookup": None, "fault": None, "latency_ms": 0.0}


class LessonTests(unittest.TestCase):
    def test_repair_stops_after_two_attempts(self) -> None:
        system = SelfImprovingSystem(repair=True)
        system.answering = ScriptedAnswering(["fixed in 1.0.0", "fixed in 2.0.0", "never used"])
        result = system.solve({"id": "t", "question": "Which version of lodash fixes CVE-2021-23337?"})
        self.assertEqual(result["n_attempts"], 2)
        self.assertEqual(result["final_result"], "REVISE")

    def test_lesson_created_after_repeat_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LessonStore(Path(tmp) / "lessons.json")
            system = SelfImprovingSystem(repair=False, lessons=store, learn=True)
            system.answering = ScriptedAnswering(["no idea", "no idea", "Upgrade to 1.2.6."])
            system.solve({"id": "a", "question": "Which version of lodash fixes CVE-2021-23337?"})
            self.assertEqual(store.lessons, [])  # seen once: not yet a repeated pattern
            second = system.solve({"id": "b", "question": "Which requests version fixes the header leak?"})
            self.assertEqual(second["lessons_created"], ["lesson_001"])
            third = system.solve({"id": "c", "question": "Which version of minimist fixes the pollution?"})
            self.assertEqual(third["lessons_loaded"], ["lesson_001"])
            saved = json.loads((Path(tmp) / "lessons.json").read_text())[0]
            self.assertEqual(saved["use_count"], 1)
            for field in ("lesson_id", "failure_pattern", "correction", "created_at", "use_count"):
                self.assertIn(field, saved)

    def test_lesson_text_for_unknown_package(self) -> None:
        lesson = lesson_for("unknown_package", Counter({"unsupported": 2}))
        self.assertEqual(lesson["applies_to"], ["any"])


if __name__ == "__main__":
    unittest.main()
