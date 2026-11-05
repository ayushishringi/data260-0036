"""HW9 Part 2: semantic cache in front of the HW8 agents, 12 queries (new, exact duplicate, paraphrase).

Starts Planner/Writer/Reviewer (grounded Writer) unless HW9_EXTERNAL_AGENTS=1, clears the cache,
asks every query through CachedQA at threshold 0.85 and prints is_cached / similarity / latency.
Writes reports/hw09/raw/part2_cache_demo.json.

Usage: make cache-demo-hw09
"""

from __future__ import annotations

import getpass
import json
import os
import socket
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HW8_LOG_DIR", str(ROOT / "reports" / "hw09" / "logs"))

from src.hw9_pipeline import AgentStack, PipelineClient  # noqa: E402
from src.redis_store import get_redis  # noqa: E402
from src.semantic_cache import DEFAULT_THRESHOLD, CachedQA, Embedder, SemanticCache  # noqa: E402

RAW = ROOT / "reports" / "hw09" / "raw"
QUERIES = [
    ("new", "What is the severity of the Log4Shell vulnerability in log4j-core?"),
    ("exact duplicate", "What is the severity of the Log4Shell vulnerability in log4j-core?"),
    ("paraphrase", "How severe is the log4j-core Log4Shell issue?"),
    ("new", "Which lodash version fixes the template command injection?"),
    ("paraphrase", "What lodash release patches the command injection in template?"),
    ("new", "How do I generate an SBOM for a Python project?"),
    ("exact duplicate", "Which lodash version fixes the template command injection?"),
    ("new", "Which requests version stops leaking the Proxy-Authorization header?"),
    ("paraphrase", "What version of requests fixes the Proxy-Authorization header leak?"),
    ("new", "What does a CWE identifier represent?"),
    ("exact duplicate", "How do I generate an SBOM for a Python project?"),
    ("paraphrase", "What is a CWE ID used for?"),
]


def main() -> None:
    print(f"user={getpass.getuser()} host={socket.gethostname()} time={datetime.now().isoformat(timespec='seconds')}")
    embedder = Embedder()
    cache = SemanticCache(get_redis())
    print(f"cleared {cache.clear()} old cache entries; threshold={DEFAULT_THRESHOLD}")
    rows = []
    with AgentStack(RAW / "runs" / "part2"):
        pipeline = PipelineClient()
        qa = CachedQA(cache, embedder, pipeline, threshold=DEFAULT_THRESHOLD)
        for n, (kind, query) in enumerate(QUERIES, 1):
            result = qa.ask(query)
            rows.append({"n": n, "kind": kind, **result})
            sim = "-" if result["similarity"] is None else f"{result['similarity']:.4f}"
            print(f"#{n:>2} {kind:<15} is_cached={str(result['is_cached']):<5} similarity={sim:<6} "
                  f"latency_ms={result['latency_ms']:>9.1f}  {query}", flush=True)
        pipeline.close()

    hits = [r for r in rows if r["is_cached"]]
    misses = [r for r in rows if not r["is_cached"]]
    summary = {
        "queries": len(rows), "hits": len(hits), "misses": len(misses),
        "hit_rate": round(len(hits) / len(rows), 4),
        "avg_latency_cached_ms": round(statistics.mean(r["latency_ms"] for r in hits), 2) if hits else None,
        "avg_latency_uncached_ms": round(statistics.mean(r["latency_ms"] for r in misses), 2) if misses else None,
        "threshold": DEFAULT_THRESHOLD, "cache_entries_after": cache.size(),
    }
    print("\n=== Cache performance ===")
    print(f"Cache hit rate: {summary['hits']}/{summary['queries']} = {summary['hit_rate']:.1%}")
    print(f"Average latency cached:     {summary['avg_latency_cached_ms']} ms")
    print(f"Average latency non-cached: {summary['avg_latency_uncached_ms']} ms")
    print("\nExample cached response:")
    example = next((r for r in rows if r["is_cached"]), rows[0])
    print(json.dumps({k: example[k] for k in ("query", "is_cached", "similarity", "latency_ms", "matched_query")},
                     indent=2))
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "part2_cache_demo.json").write_text(json.dumps(
        {"ran_at": datetime.now().isoformat(timespec="seconds"), "summary": summary, "results": rows},
        indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
