#!/usr/bin/env python3
"""Run 20 pipelines at 0.7 and 20 at 0.0; write CSV/JSON and METRICS snippet."""

from __future__ import annotations

import csv
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from agents_demo import run_pipeline  # noqa: E402
from model_client import ModelClient  # noqa: E402


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def summarize(runs: list[dict]) -> dict:
    tag_sets = [tuple(r["tags"]) for r in runs]
    distinct = len(set(tag_sets))
    freq = Counter(tag for tags in tag_sets for tag in tags)
    n = len(runs)
    in_all = sorted([t for t, c in freq.items() if c == n])
    in_one = sorted([t for t, c in freq.items() if c == 1])
    lat = [r["latency_ms"] for r in runs]
    return {
        "distinct_tag_sets": distinct,
        "tags_in_all_runs": in_all,
        "tags_in_exactly_one_run": in_one,
        "latency_p50_ms": round(percentile(lat, 50), 1),
        "latency_p95_ms": round(percentile(lat, 95), 1),
        "latency_p99_ms": round(percentile(lat, 99), 1),
        "latency_mean_ms": round(statistics.mean(lat), 1) if lat else 0,
    }


def run_batch(client: ModelClient, title: str, content: str, temperature: float, n: int) -> list[dict]:
    rows = []
    for i in range(n):
        started = time.perf_counter()
        result = run_pipeline(title, content, temperature, client)
        elapsed_ms = (time.perf_counter() - started) * 1000
        row = {
            "run": i + 1,
            "temperature": temperature,
            "latency_ms": round(elapsed_ms, 2),
            "tags": result["publish"]["tags"],
            "summary": result["publish"]["summary"],
        }
        rows.append(row)
        print(f"temp={temperature} run={i + 1}/{n} {elapsed_ms:.0f}ms tags={row['tags']}", flush=True)
    return rows


def main() -> int:
    case = json.loads((ROOT / "reports/hw01/cases/nondeterminism_input.json").read_text())
    client = ModelClient()
    raw_dir = ROOT / "reports/hw01/raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    all_rows = []
    all_rows.extend(run_batch(client, case["title"], case["content"], 0.7, 20))
    all_rows.extend(run_batch(client, case["title"], case["content"], 0.0, 20))

    json_path = raw_dir / "nondeterminism_40_runs.json"
    csv_path = raw_dir / "nondeterminism_40_runs.csv"
    json_path.write_text(json.dumps(all_rows, indent=2) + "\n")
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["run", "temperature", "latency_ms", "tags", "summary"])
        writer.writeheader()
        for row in all_rows:
            writer.writerow(
                {
                    **row,
                    "tags": json.dumps(row["tags"]),
                }
            )

    metrics = {
        "0.7": summarize([r for r in all_rows if r["temperature"] == 0.7]),
        "0.0": summarize([r for r in all_rows if r["temperature"] == 0.0]),
    }
    (raw_dir / "nondeterminism_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
