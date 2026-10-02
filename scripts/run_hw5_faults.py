from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

from hw5_tools.domain import VERIFY_SEED, fault_injection_call

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "reports" / "hw05" / "raw"


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    rows = [fault_injection_call(rate, call, VERIFY_SEED) for rate in (0.0, 0.2, 0.5) for call in range(1, 51)]
    with (RAW / "fault_injection.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader(); writer.writerows(rows)
    (RAW / "fault_injection.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    summaries = []
    for rate in (0.0, 0.2, 0.5):
        subset = [r for r in rows if r["rate"] == rate]
        latencies = sorted(r["latency_ms"] for r in subset)
        summaries.append({"rate": rate, "success_rate": round(sum(r["status"] == "success" for r in subset) / 50, 4),
                          "mean_latency_ms": round(statistics.mean(latencies), 4),
                          "p99_latency_ms": round(latencies[min(49, int(0.99 * len(latencies)))], 4)})
    (RAW / "fault_summary.json").write_text(json.dumps({"seed": VERIFY_SEED, "rows": summaries}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
