"""HW9 Part 3.2: threshold sweep over the 40 labeled cases in cache_cases.yaml.

1. Clear the cache and cache the 10 seed queries through the HW8 agents (only approved answers are cached).
2. For each threshold, ask all 40 cases against that same seeded cache with store_on_miss=False,
   so every threshold sees an identical cache. Misses run the full agent pipeline (real latency).
3. Score each case: correct hit, false hit (hit whose cached answer is wrong for the query),
   missed hit (should have hit), correct miss.
Writes reports/hw09/raw/sweep_results.json (merged per threshold, so a crash keeps finished thresholds).

Usage: make sweep-hw09            (or: --thresholds 0.85 0.90 to rerun some)
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import socket
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HW8_LOG_DIR", str(ROOT / "reports" / "hw09" / "logs"))

from src.hw9_pipeline import AgentStack, PipelineClient  # noqa: E402
from src.redis_store import get_redis  # noqa: E402
from src.semantic_cache import CachedQA, Embedder, SemanticCache  # noqa: E402

CASES = ROOT / "cache_cases.yaml"
RAW = ROOT / "reports" / "hw09" / "raw"
OUTPUT = RAW / "sweep_results.json"
THRESHOLDS = [0.75, 0.80, 0.85, 0.90, 0.95]


def score(case: dict, result: dict, seeds: dict[str, str]) -> str:
    """Outcome of one case: correct_hit, false_hit, missed_hit or correct_miss."""

    if result["is_cached"]:
        if case["expected"] == "hit" and result["matched_query"] == seeds[case["target"]]:
            return "correct_hit"
        return "false_hit"
    return "missed_hit" if case["expected"] == "hit" else "correct_miss"


def summarize(threshold: float, rows: list[dict]) -> dict:
    """Hit rate, false-hit rate and latency for one threshold."""

    n = len(rows)
    count = {k: sum(r["outcome"] == k for r in rows) for k in ("correct_hit", "false_hit", "missed_hit",
                                                                "correct_miss")}
    hits = [r for r in rows if r["is_cached"]]
    misses = [r for r in rows if not r["is_cached"]]
    return {"threshold": threshold, "queries": n, "hits": len(hits), "misses": len(misses), **count,
            "hit_rate": round(len(hits) / n, 4), "false_hit_rate": round(count["false_hit"] / n, 4),
            "false_hits_per_hit": round(count["false_hit"] / len(hits), 4) if hits else 0.0,
            "mean_latency_ms": round(statistics.mean(r["latency_ms"] for r in rows), 2),
            "mean_hit_latency_ms": round(statistics.mean(r["latency_ms"] for r in hits), 2) if hits else None,
            "mean_miss_latency_ms": round(statistics.mean(r["latency_ms"] for r in misses), 2) if misses else None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--thresholds", type=float, nargs="*", default=THRESHOLDS)
    args = parser.parse_args()
    spec = yaml.safe_load(CASES.read_text())
    seeds = {s["id"]: s["query"] for s in spec["seed_queries"]}
    cases = spec["cases"]
    assert len(cases) == 40, "cache_cases.yaml must hold 40 cases"
    cases_sha = hashlib.sha256(CASES.read_bytes()).hexdigest()
    committed = subprocess.run(["git", "log", "-1", "--format=%h %cI", "--", "cache_cases.yaml"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
    print(f"user={getpass.getuser()} host={socket.gethostname()} time={datetime.now().isoformat(timespec='seconds')}")
    print(f"cache_cases.yaml sha256={cases_sha[:16]} last commit: {committed or 'not committed'}")

    data = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {}
    if data.get("cases_sha256") not in (None, cases_sha):
        data = {}  # results from another version of the file are not mixed in
    data.update({"cases_sha256": cases_sha, "cases_commit": committed or None})
    data.setdefault("thresholds", {})

    embedder = Embedder()
    cache = SemanticCache(get_redis())
    with AgentStack(RAW / "runs" / "sweep"):
        pipeline = PipelineClient()
        print(f"\n=== Seeding cache (cleared {cache.clear()} entries) ===")
        seeder = CachedQA(cache, embedder, pipeline, threshold=0.999, component="sweep-seed")
        seed_rows = []
        for sid, query in seeds.items():
            for attempt in range(1, 4):
                result = seeder.ask(query)
                if result.get("status") == "approved":
                    break
                print(f"  {sid} not approved (attempt {attempt}), asking again")
            seed_rows.append({"id": sid, "attempts": attempt, **result})
            print(f"  {sid} cached={result.get('status') == 'approved'} latency_ms={result['latency_ms']:.0f} {query}",
                  flush=True)
        data["seeds"] = seed_rows
        data["seeded_at"] = datetime.now().isoformat(timespec="seconds")
        print(f"cache entries: {cache.size()}")

        for threshold in args.thresholds:
            print(f"\n=== Threshold {threshold:.2f} ===")
            qa = CachedQA(cache, embedder, pipeline, threshold=threshold, store_on_miss=False,
                          component=f"sweep-{threshold:.2f}")
            rows = []
            for case in cases:
                result = qa.ask(case["query"])
                row = {**{k: case.get(k) for k in ("id", "category", "expected", "target", "near")}, **result,
                       "outcome": score(case, result, seeds)}
                rows.append(row)
                print(f"  {case['id']} {case['category']:<17} exp={case['expected']:<4} sim={result['similarity']:.4f} "
                      f"cached={str(result['is_cached']):<5} {row['outcome']:<12} {result['latency_ms']:>9.1f} ms",
                      flush=True)
            summary = summarize(threshold, rows)
            data["thresholds"][f"{threshold:.2f}"] = {"summary": summary, "rows": rows,
                                                      "ran_at": datetime.now().isoformat(timespec="seconds")}
            OUTPUT.write_text(json.dumps(data, indent=2, default=str) + "\n")
            print(f"  -> hit rate {summary['hit_rate']:.1%}, false-hit rate {summary['false_hit_rate']:.1%}, "
                  f"mean latency {summary['mean_latency_ms']:.0f} ms")
        pipeline.close()
    print(f"\nwrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
