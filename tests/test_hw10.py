"""HW10 unit tests: spans, evaluator join/bounds, statistics, traced cache path. No Kafka/Ollama needed."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from scipy.stats import spearmanr

from src import advisory_lookup, tracing
from src.evaluator import Evaluator, interpret
from src.hw10_stats import eval_summary, judge_vs_human, repeatability, stage_latency, summary
from src.judge import METRIC_SPECS, OllamaJudge, make_metric, score_1_5
from src.kafka_common import DEAD_LETTER_TOPIC, DRAFTS_TOPIC, FINAL_TOPIC, TASKS_TOPIC
from src.semantic_cache import CachedQA
from tests.test_hw9 import FakeCache, FakeEmbedder


class SpanFileCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.span_path = Path(self.tmp.name) / "spans.jsonl"
        patcher = mock.patch.dict(os.environ, {"HW10_TRACE": "1", "HW10_SPAN_FILE": str(self.span_path)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def spans(self) -> list[dict]:
        return tracing.load_spans(self.span_path)


class TracingTests(SpanFileCase):
    def test_span_has_required_fields(self) -> None:
        tracing.write_span("t1", "planner", 100.0, 100.5, component="planner", attempt=1)
        (s,) = self.spans()
        for field in ("trace_id", "stage", "start_time", "end_time", "status", "error", "duration_ms"):
            self.assertIn(field, s)
        self.assertEqual((s["trace_id"], s["stage"], s["status"], s["duration_ms"]), ("t1", "planner", "ok", 500.0))

    def test_context_manager_records_error_and_reraises(self) -> None:
        with self.assertRaises(ValueError):
            with tracing.span("t2", "writer"):
                raise ValueError("boom")
        (s,) = self.spans()
        self.assertEqual(s["status"], "error")
        self.assertIn("boom", s["error"])

    def test_disabled_writes_nothing(self) -> None:
        with mock.patch.dict(os.environ, {"HW10_TRACE": "0"}):
            tracing.write_span("t3", "planner", 1.0, 2.0)
        self.assertEqual(self.spans(), [])

    def test_trace_orders_by_start(self) -> None:
        tracing.write_span("t", "writer", 2.0, 3.0)
        tracing.write_span("t", "cache_lookup", 0.0, 0.1)
        tracing.write_span("other", "planner", 0.5, 1.0)
        self.assertEqual([s["stage"] for s in tracing.trace(self.spans(), "t")], ["cache_lookup", "writer"])


def fake_judge(scores: dict[str, float] | None = None):
    calls = []

    def judge(key, question, output, context=None, timeout=None):
        calls.append((key, output))
        return {"score": (scores or {}).get(key, 4.0), "reason": f"{key} ok", "status": "ok", "error": None,
                "judge_ms": 1.0}
    judge.calls = calls
    return judge


class EvaluatorTests(SpanFileCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch("src.evaluator.log")
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, judge=None, **kw) -> Evaluator:
        return Evaluator(judge_fn=judge or fake_judge(), available=lambda: True,
                         sink=Path(self.tmp.name) / "evals.jsonl", **kw)

    def feed(self, ev: Evaluator, cid: str = "c1", draft: str = "draft text", answer: str = "draft text"):
        meta = {"partition": 0, "offset": 1}
        out = [ev.on_message(FINAL_TOPIC, {"correlation_id": cid, "answer": answer, "status": "approved",
                                           "question": "q?"}, meta),
               ev.on_message(TASKS_TOPIC, {"correlation_id": cid, "question": "q?", "plan": ["a", "b"]}, meta),
               ev.on_message(DRAFTS_TOPIC, {"correlation_id": cid, "question": "q?", "draft": draft,
                                            "facts": ["fact"]}, meta)]
        return out

    def test_joins_on_correlation_id_in_any_order(self) -> None:
        judge = fake_judge({"final_helpfulness": 4.0})
        ev = self.make(judge)
        first, second, record = self.feed(ev)
        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(record["outcome"], "evaluated")
        self.assertEqual(record["writer_helpfulness"]["trace_id"], "c1")
        self.assertEqual(record["final_helpfulness"]["final_answer"], "draft text")
        self.assertEqual(record["plan_quality"]["reason"], "plan_quality ok")
        self.assertEqual(record["final_vs_draft"]["difference"], 0.0)
        self.assertTrue(record["final_vs_draft"]["draft_equals_final"])
        self.assertIn("No improvement", record["final_vs_draft"]["interpretation"])
        self.assertEqual(record["messages"]["plan"]["_kafka"]["topic"], TASKS_TOPIC)
        self.assertEqual(len(judge.calls), 4)
        (span,) = [s for s in self.spans() if s["stage"] == "evaluation"]
        self.assertEqual((span["trace_id"], span["status"]), ("c1", "ok"))

    def test_other_correlation_ids_do_not_mix(self) -> None:
        ev = self.make()
        meta = {"partition": 0, "offset": 1}
        ev.on_message(TASKS_TOPIC, {"correlation_id": "a", "question": "q", "plan": ["x"]}, meta)
        ev.on_message(DRAFTS_TOPIC, {"correlation_id": "b", "question": "q", "draft": "d"}, meta)
        self.assertIsNone(ev.on_message(FINAL_TOPIC, {"correlation_id": "a", "answer": "d"}, meta))
        self.assertEqual(set(ev.pending), {"a", "b"})

    def test_dead_letter_closes_join_without_judging(self) -> None:
        judge = fake_judge()
        ev = self.make(judge)
        ev.on_message(TASKS_TOPIC, {"correlation_id": "c", "question": "q", "plan": ["x"]}, {})
        record = ev.on_message(DEAD_LETTER_TOPIC, {"correlation_id": "c", "failed_agent": "writer", "attempts": 3,
                                                   "error": "timeout"}, {})
        self.assertEqual((record["outcome"], record["status"]), ("not_evaluated", "error"))
        self.assertIn("writer", record["error"])
        self.assertEqual(judge.calls, [])
        (span,) = [s for s in self.spans() if s["stage"] == "evaluation"]
        self.assertEqual(span["failed_stage"], "writer")

    def test_incomplete_join_expires(self) -> None:
        ev = self.make(join_timeout=5)
        ev.on_message(TASKS_TOPIC, {"correlation_id": "c", "question": "q", "plan": ["x"]}, {})
        self.assertEqual(ev.expire(time.time() + 1), [])
        (record,) = ev.expire(time.time() + 10)
        self.assertEqual(record["outcome"], "incomplete")
        self.assertIn("draft", record["error"])
        self.assertEqual(ev.pending, {})

    def test_malformed_message_is_skipped(self) -> None:
        ev = self.make()
        self.assertIsNone(ev.on_message(TASKS_TOPIC, ["not", "an", "object"], {}))
        self.assertIsNone(ev.on_message(TASKS_TOPIC, {"no_id": 1}, {}))
        self.assertEqual(ev.pending, {})

    def test_unavailable_judge_fails_fast(self) -> None:
        judge = fake_judge()
        ev = Evaluator(judge_fn=judge, available=lambda: False, sink=Path(self.tmp.name) / "e.jsonl")
        *_, record = self.feed(ev)
        self.assertEqual(record["status"], "error")
        self.assertEqual(record["plan_quality"]["error"], "judge unavailable")
        self.assertEqual(judge.calls, [])

    def test_budget_bounds_the_evaluation(self) -> None:
        judge = fake_judge()
        ev = self.make(judge, budget=0)
        *_, record = self.feed(ev)
        self.assertIn("budget", record["writer_helpfulness"]["error"])
        self.assertEqual(judge.calls, [])


class InterpretTests(unittest.TestCase):
    def test_identical_text_is_not_improvement(self) -> None:
        self.assertIn("No improvement", interpret(4, 4, True, "approved"))
        self.assertIn("judge variance", interpret(4, 5, True, "approved"))

    def test_changed_text(self) -> None:
        self.assertIn("Improved", interpret(3, 4, False, "approved"))
        self.assertIn("Regressed", interpret(4, 3, False, "approved"))
        self.assertIn("Not compared", interpret(None, 4, False, "approved"))


class JudgeTests(unittest.TestCase):
    def test_rubric_is_1_to_5(self) -> None:
        with mock.patch.object(OllamaJudge, "__init__", lambda self, *a, **k: None):
            judge = OllamaJudge()
            judge.client = mock.Mock(model="qwen3:4b")
            judge.name = "qwen3:4b"
            for key in METRIC_SPECS:
                metric = make_metric(key, judge)
                self.assertEqual(metric.score_range, (1, 5))
                self.assertEqual(len(metric.evaluation_steps), len(METRIC_SPECS[key]["steps"]))

    def test_missing_context_gets_explicit_no_record(self) -> None:
        from src import judge as judge_module
        seen = {}

        class FakeMetric:
            reason = "ok"

            def measure(self, case, _show_indicator=False):
                seen["context"] = case.retrieval_context
                return 0.75
        with mock.patch.object(judge_module, "make_metric", return_value=FakeMetric()):
            result = judge_module.evaluate("writer_helpfulness", "q", "draft", [], judge=mock.Mock())
        self.assertEqual((result["score"], seen["context"]), (4.0, [judge_module.NO_RECORD]))

    def test_score_mapping(self) -> None:
        self.assertEqual([score_1_5(x) for x in (0.0, 0.25, 0.5, 1.0)], [1.0, 2.0, 3.0, 5.0])


class StatsTests(unittest.TestCase):
    def test_judge_vs_human_matches_scipy(self) -> None:
        human = [1, 2, 3, 4, 5, 3, 4, 2]
        judge = [2, 2, 3, 5, 4, 4, 4, 1]
        r = judge_vs_human(human, judge)
        self.assertAlmostEqual(r["spearman_rho"], round(spearmanr(human, judge)[0], 4))
        self.assertAlmostEqual(r["mean_abs_diff"], float(np.mean(np.abs(np.subtract(human, judge)))))

    def test_repeatability(self) -> None:
        r = repeatability([[4, 3, 5, 2], [4, 4, 5, 2], [4, 3, 5, 4]])
        self.assertEqual((r["cases_changed"], r["change_rate"]), (2, 0.5))
        self.assertEqual(r["max_abs_change"], 2)
        self.assertEqual(r["pairwise_comparisons"], 12)
        self.assertEqual(r["pairwise_changes"], 4)

    def synthetic(self, tid: str, base: float, path: str = "miss") -> list[dict]:
        def s(stage, a, b, **kw):
            return {"trace_id": tid, "stage": stage, "start_ts": base + a, "end_ts": base + b,
                    "start_time": "2026-11-11T10:00:00", "duration_ms": (b - a) * 1000, "status": "ok", **kw}
        return [s("request", 0, 9, path=path), s("cache_lookup", 0, 0.1, result=path), s("queue_inbox", 0.1, 0.2),
                s("planner", 0.2, 2), s("queue_tasks", 2, 2.1), s("writer", 2.1, 8), s("queue_drafts", 8, 8.1),
                s("reviewer", 8.1, 8.2), s("queue_final", 8.2, 8.3), s("evaluation", 9, 20)]

    def test_stage_latency_shares_sum_to_one(self) -> None:
        spans = self.synthetic("a", 0) + self.synthetic("b", 100)
        r = stage_latency(spans)
        self.assertEqual(r["traces"], 2)
        self.assertAlmostEqual(sum(t["share_of_e2e"] for t in r["table"]), 1.0, places=3)
        self.assertEqual(r["dominant"], "Evaluation")
        queue = next(t for t in r["table"] if t["key"] == "queue_wait_total")
        self.assertAlmostEqual(queue["p50_ms"], 400.0, places=1)

    def test_hits_are_excluded_from_miss_latency_and_counted_in_summary(self) -> None:
        hit = [{"trace_id": "h", "stage": "request", "start_ts": 5.0, "end_ts": 5.01, "start_time": "x",
                "duration_ms": 10.0, "status": "ok", "path": "hit"},
               {"trace_id": "h", "stage": "cache_lookup", "start_ts": 5.0, "end_ts": 5.01, "start_time": "x",
                "duration_ms": 10.0, "status": "ok", "result": "hit"}]
        failed = [{"trace_id": "f", "stage": "request", "start_ts": 6.0, "end_ts": 7.0, "start_time": "y",
                   "duration_ms": 1000.0, "status": "error", "path": "miss"}]
        spans = self.synthetic("a", 0) + hit + failed
        self.assertEqual(stage_latency(spans)["traces"], 1)
        s = summary(spans)
        self.assertEqual((s["requests"], s["hits"], s["misses"], s["errors"]), (3, 1, 2, 1))
        self.assertEqual(s["latency_hit"]["p50_ms"], 10.0)
        self.assertEqual(s["latency_miss"]["n"], 1)

    def test_eval_summary(self) -> None:
        rec = {"outcome": "evaluated", "plan_quality": {"score": 3.0}, "writer_helpfulness": {"score": 4.0},
               "final_helpfulness": {"score": 2.0, "review_status": "approved"},
               "final_vs_draft": {"difference": 0.0, "draft_equals_final": True}}
        s = eval_summary([rec, {"outcome": "not_evaluated"}])
        self.assertEqual((s["evaluated"], s["not_evaluated"], s["approved_but_low"]), (1, 1, 1))


class FakePipeline:
    def __init__(self) -> None:
        self.ids: list[str | None] = []

    def ask(self, question: str, timeout: float = 300, correlation_id: str | None = None) -> dict:
        self.ids.append(correlation_id)
        return {"correlation_id": correlation_id or "x", "status": "approved", "answer": "a"}


class TracedCacheTests(SpanFileCase):
    def setUp(self) -> None:
        super().setUp()
        for p in [mock.patch.object(advisory_lookup, "find_records", return_value=[{"id": 5}]),
                  mock.patch.object(advisory_lookup, "data_version", return_value="v-1"),
                  mock.patch.object(advisory_lookup, "current_version", return_value="v-1"),
                  mock.patch("src.semantic_cache.log")]:
            p.start()
            self.addCleanup(p.stop)

    def test_trace_id_is_the_correlation_id_and_hit_miss_are_spanned(self) -> None:
        pipeline = FakePipeline()
        qa = CachedQA(FakeCache(), FakeEmbedder(), pipeline, threshold=0.85)
        qa.ask("Which lodash version fixes it?", trace_id="trace-1")
        qa.ask("Which lodash version fixes it?", trace_id="trace-2")
        self.assertEqual(pipeline.ids, ["trace-1"])  # the cache miss sent the same id into Kafka
        lookups = {s["trace_id"]: s["result"] for s in self.spans() if s["stage"] == "cache_lookup"}
        self.assertEqual(lookups, {"trace-1": "miss", "trace-2": "hit"})


if __name__ == "__main__":
    unittest.main()
