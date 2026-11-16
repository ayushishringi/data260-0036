"""HW10 Part 4.3: stage-latency experiment on 50 confirmed cache misses (+ cache hits, reported separately).

Builds 115 new grounded questions (5 templates x 23 advisory packages), keeps the ones whose nearest
cached query is below the 0.85 threshold, and sends 50 of them (seeded order, SEED 36) one at a time
through the traced path: cache lookup -> inbox -> planner -> tasks -> writer -> drafts -> reviewer ->
final -> evaluator. The cache does not store these answers (store_on_miss=False), so no request can be
answered by an earlier one; the cache_lookup span of every trace is checked to be a miss. Each request
waits for its evaluation span before the next starts, so stages never compete for the local model.
Then 10 cached queries are asked again to measure cache-hit latency on its own.

Writes reports/hw10/raw/latency_run.json and latency_requests.jsonl.

Usage: make latency-hw10
"""

from __future__ import annotations

import getpass
import json
import os
import random
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HW8_LOG_DIR", str(ROOT / "reports" / "hw10" / "logs"))
os.environ["HW10_TRACE"] = "1"

from src import tracing  # noqa: E402
from src.advisory_lookup import all_records  # noqa: E402
from src.hw10_pipeline import TracedPipelineClient, hw10_stack, traced_request, uncached, wait_for_evaluation  # noqa: E402
from src.hw10_stats import stage_latency, pct  # noqa: E402
from src.redis_store import get_redis  # noqa: E402
from src.semantic_cache import DEFAULT_THRESHOLD, CachedQA, Embedder, SemanticCache  # noqa: E402

RAW = ROOT / "reports" / "hw10" / "raw"
N_MISSES, N_HITS, SEED = 50, 10, 36
TEMPLATES = [
    "Explain to a junior developer what the {cve} issue in {pkg} lets an attacker do.",
    "What compensating controls can we use until {pkg} can be upgraded past the {cve} fix?",
    "How would a CI pipeline detect that a project still depends on a vulnerable {pkg}?",
    "Write a short risk note for management about {cve} in {pkg}.",
    "Which of our services should we patch first if they all use {pkg}, given {cve}?",
]


def candidates() -> list[str]:
    out = []
    for record in all_records():
        cve = record["description"].split(":")[0]
        out += [t.format(pkg=record["package_name"], cve=cve) for t in TEMPLATES]
    random.Random(SEED).shuffle(out)
    return out


def main() -> None:
    print(f"user={getpass.getuser()} host={socket.gethostname()} time={datetime.now().isoformat(timespec='seconds')}")
    cache, embedder = SemanticCache(get_redis()), Embedder()
    log_file = RAW / "latency_requests.jsonl"
    log_file.unlink(missing_ok=True)
    rows, hit_rows = [], []
    started = time.time()
    with hw10_stack(RAW / "runs" / "latency"):
        pipeline = TracedPipelineClient()
        qa = CachedQA(cache, embedder, pipeline, threshold=DEFAULT_THRESHOLD, store_on_miss=False,
                      component="hw10-latency")
        pool = uncached(qa, candidates())
        print(f"{len(pool)} of {len(candidates())} candidate questions are below the {DEFAULT_THRESHOLD} threshold; "
              f"using the first {N_MISSES}", flush=True)
        for n, (question, best) in enumerate(pool[:N_MISSES], 1):
            r = traced_request(qa, question, experiment="latency-miss", best_cached_similarity=best)
            ev = wait_for_evaluation(r["trace_id"]) if r["status"] == "ok" else None
            row = {"n": n, "trace_id": r["trace_id"], "question": question, "status": r["status"],
                   "is_cached": r.get("is_cached"), "similarity": r.get("similarity"), "latency_ms": r["latency_ms"],
                   "evaluation_status": ev and ev["status"], "evaluation_ms": ev and ev["duration_ms"],
                   "error": r.get("error")}
            rows.append(row)
            with log_file.open("a") as stream:
                stream.write(json.dumps(row) + "\n")
            print(f"miss {n:>2}/{N_MISSES} is_cached={row['is_cached']} sim={row['similarity']} "
                  f"answer={row['latency_ms'] / 1000:6.1f}s eval={(row['evaluation_ms'] or 0) / 1000:6.1f}s "
                  f"{row['status']}  {question[:70]}", flush=True)
        # Cache-hit latency, measured separately: re-ask queries that are in the cache verbatim.
        cached = [k for k in cache.r.scan_iter(match=f"{cache.key_prefix}*", count=500)]
        queries = sorted({cache.r.hget(k, "query").decode() for k in cached})
        if not queries:
            raise SystemExit("the cache is empty; run make e2e-hw10 first so there are entries to hit")
        picks = [queries[i % len(queries)] for i in range(N_HITS)]  # cycle when fewer than N_HITS entries
        for n, question in enumerate(picks, 1):
            r = traced_request(qa, question, experiment="latency-hit")
            hit_rows.append({"n": n, "trace_id": r["trace_id"], "question": question, "is_cached": r.get("is_cached"),
                             "similarity": r.get("similarity"), "latency_ms": r["latency_ms"], "status": r["status"]})
            print(f"hit {n:>2}/{N_HITS} is_cached={r.get('is_cached')} latency={r['latency_ms']:.1f} ms", flush=True)
        pipeline.close()

    spans = tracing.load_spans()
    ids = [r["trace_id"] for r in rows]
    lookups = {s["trace_id"]: s.get("result") for s in spans if s["stage"] == "cache_lookup" and s["trace_id"] in ids}
    verified = {"requests": len(rows), "cache_lookup_miss": sum(v == "miss" for v in lookups.values()),
                "served_from_cache": sum(bool(r["is_cached"]) for r in rows),
                "failed": sum(r["status"] != "ok" for r in rows)}
    stats = stage_latency(spans, ids)
    hits_ok = [r["latency_ms"] for r in hit_rows if r["is_cached"]]
    hit_stats = {"n": len(hits_ok), "p50_ms": pct(hits_ok, 50), "p95_ms": pct(hits_ok, 95)}
    result = {"ran_at": datetime.now().isoformat(timespec="seconds"), "duration_s": round(time.time() - started),
              "threshold": DEFAULT_THRESHOLD, "verification": verified, "stage_latency": stats,
              "cache_hit_latency": hit_stats, "requests": rows, "hit_requests": hit_rows}
    (RAW / "latency_run.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(f"\nverified: {verified}")
    print(f"\n{'Stage':<22}{'p50 (ms)':>12}{'p95 (ms)':>12}{'% of e2e':>10}")
    for t in stats["table"]:
        print(f"{t['stage']:<22}{t['p50_ms']:>12,.1f}{t['p95_ms']:>12,.1f}{(t['share_of_e2e'] or 0):>10.1%}")
    print(f"{'End-to-end':<22}{stats['end_to_end']['p50_ms']:>12,.1f}{stats['end_to_end']['p95_ms']:>12,.1f}")
    print(f"dominant stage: {stats['dominant']}   cache-hit latency: {hit_stats}")


if __name__ == "__main__":
    main()
