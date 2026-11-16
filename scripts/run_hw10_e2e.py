"""HW10 Parts 2 + 4.2: end-to-end evaluation run and the three required trace examples.

Starts Planner/Writer/Reviewer + evaluator (tracing on), then through CachedQA (threshold 0.85):
  1-3  three new questions (cache misses) -> agents -> evaluator scores plan, draft, final
  4    question 1 again                    -> cache hit (no agents, no evaluation)
  5    a new question with inject_fault=writer -> Writer fails 3 attempts -> s0036_dead_letter
Writes reports/hw10/raw/e2e_run.json (results + evaluation records) and trace_examples.json.

Usage: make e2e-hw10
"""

from __future__ import annotations

import getpass
import json
import os
import socket
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HW8_LOG_DIR", str(ROOT / "reports" / "hw10" / "logs"))
os.environ["HW10_TRACE"] = "1"

from src import tracing  # noqa: E402
from src.hw10_pipeline import TracedPipelineClient, hw10_stack, traced_request, uncached, wait_for_evaluation  # noqa: E402
from src.redis_store import get_redis  # noqa: E402
from src.semantic_cache import DEFAULT_THRESHOLD, CachedQA, Embedder, SemanticCache  # noqa: E402

RAW = ROOT / "reports" / "hw10" / "raw"
EVAL_QUESTIONS = [
    "Which jackson-databind release fixes the deeply nested JSON denial of service, and how severe is it?",
    "Is golang.org/x/net 0.15.0 affected by the HTTP/2 rapid reset attack, and what should I upgrade to?",
    "Why should a team generate a software bill of materials for every release?",
]
FAIL_QUESTION = "Which follow-redirects version stops keeping the Proxy-Authorization header across hosts?"


def show(n: int, label: str, r: dict) -> None:
    sim = "-" if r.get("similarity") is None else f"{r['similarity']:.4f}"
    print(f"#{n} {label:<22} trace_id={r['trace_id']} status={r['status']:<5} is_cached={r.get('is_cached')!s:<5} "
          f"similarity={sim:<6} latency_ms={r['latency_ms']:>9.1f}", flush=True)
    if r["status"] == "error":
        print(f"   error: {r['error']}")


def main() -> None:
    print(f"user={getpass.getuser()} host={socket.gethostname()} time={datetime.now().isoformat(timespec='seconds')}")
    print(f"spans -> {tracing.span_file().relative_to(ROOT)}")
    qa_cache = SemanticCache(get_redis())
    embedder = Embedder()
    results, evaluations = [], []
    with hw10_stack(RAW / "runs" / "e2e"):
        pipeline = TracedPipelineClient()
        qa = CachedQA(qa_cache, embedder, pipeline, threshold=DEFAULT_THRESHOLD, component="hw10-e2e")
        fresh = uncached(qa, EVAL_QUESTIONS + [FAIL_QUESTION])
        if len(fresh) != len(EVAL_QUESTIONS) + 1:
            raise SystemExit(f"some questions are already cached: {fresh}")
        for n, question in enumerate(EVAL_QUESTIONS, 1):
            r = traced_request(qa, question, demo="part2-eval")
            show(n, "cache miss + evaluate", r)
            span = wait_for_evaluation(r["trace_id"]) if r["status"] == "ok" else None
            print(f"   evaluation span: {span and span['status']} {span and span['duration_ms']} ms "
                  f"scores={span and span.get('scores')}", flush=True)
            results.append({"n": n, "role": "cache_miss_eval", **r})
        r = traced_request(qa, EVAL_QUESTIONS[0], demo="cache-hit")
        show(4, "repeat -> cache hit", r)
        results.append({"n": 4, "role": "cache_hit", **r})
        pipeline.inject_fault = "writer"
        r = traced_request(qa, FAIL_QUESTION, demo="failed-trace")
        pipeline.inject_fault = None
        show(5, "injected writer fault", r)
        span = wait_for_evaluation(r["trace_id"], timeout=60)
        print(f"   evaluator saw the failure: {span and span['error']}")
        results.append({"n": 5, "role": "failed", **r})
        pipeline.close()

    ids = {r["trace_id"] for r in results}
    eval_file = ROOT / "reports" / "hw10" / "raw" / "evaluations.jsonl"
    for line in eval_file.read_text().splitlines() if eval_file.exists() else []:
        record = json.loads(line)
        if record["trace_id"] in ids:
            evaluations.append(record)
    miss = results[0]
    examples = {
        "cache_hit": {"trace_id": results[3]["trace_id"], "question": results[3]["query"],
                      "description": "repeat of question 1, answered from the Redis semantic cache"},
        "cache_miss": {"trace_id": miss["trace_id"], "question": miss["query"],
                       "description": "new question: cache miss -> planner -> writer -> reviewer -> evaluator"},
        "failed": {"trace_id": results[4]["trace_id"], "question": FAIL_QUESTION,
                   "failed_stage": results[4].get("failed_stage"), "error": results[4].get("error"),
                   "description": "inject_fault=writer: Writer fails 3 attempts, message goes to s0036_dead_letter"},
    }
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "trace_examples.json").write_text(json.dumps(examples, indent=2) + "\n")
    (RAW / "e2e_run.json").write_text(json.dumps(
        {"ran_at": datetime.now().isoformat(timespec="seconds"), "threshold": DEFAULT_THRESHOLD,
         "results": results, "evaluations": evaluations}, indent=2, default=str) + "\n")
    print("\n=== Evaluation results (1-5) ===")
    for e in evaluations:
        if e["outcome"] != "evaluated":
            print(f"{e['trace_id']}  {e['outcome']}: {e['error']}")
            continue
        fv = e["final_vs_draft"]
        print(f"{e['trace_id']}  plan={e['plan_quality']['score']} writer={e['writer_helpfulness']['score']} "
              f"final={e['final_helpfulness']['score']} draft={fv['draft_score']} diff={fv['difference']}")
        print(f"   {fv['interpretation']}")
    print("\n=== Trace examples ===")
    for kind, ex in examples.items():
        print(f"{kind:<10} {ex['trace_id']}")


if __name__ == "__main__":
    main()
