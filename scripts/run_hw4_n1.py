import csv
import json
import os
import statistics
import time
from datetime import datetime, timezone

from sqlalchemy import event, select
from sqlalchemy.orm import selectinload

from backend.database import db_session_basede26, engine
from backend.models import VulnerabilityReport


PAGE_SIZES = [10, 50, 200]
RUNS = 30
WARMUPS = 2

OUTPUT_DIR = "reports/hw04/raw"
CSV_PATH = f"{OUTPUT_DIR}/n1_benchmark.csv"
JSON_PATH = f"{OUTPUT_DIR}/n1_benchmark.json"


def run_naive(page_size: int) -> tuple[float, int, int]:
    """
    Naive version:
    One query loads reports.
    Then accessing report.advisories causes one query per report.
    """

    db = db_session_basede26()
    query_counter = {"count": 0}

    def count_query(*args, **kwargs):
        query_counter["count"] += 1

    event.listen(engine, "before_cursor_execute", count_query)

    try:
        start = time.perf_counter()

        reports = db.scalars(
            select(VulnerabilityReport)
            .where(
                VulnerabilityReport.package_name.like(
                    "hw4-n1-package-%"
                )
            )
            .order_by(VulnerabilityReport.id)
            .limit(page_size)
        ).all()

        advisory_count = sum(
            len(report.advisories)
            for report in reports
        )

        elapsed_ms = (time.perf_counter() - start) * 1000

        return (
            elapsed_ms,
            query_counter["count"],
            advisory_count,
        )

    finally:
        event.remove(engine, "before_cursor_execute", count_query)
        db.close()


def run_fixed(page_size: int) -> tuple[float, int, int]:
    """
    Fixed version:
    selectinload fetches all related advisories in one additional query,
    instead of one query per report.
    """

    db = db_session_basede26()
    query_counter = {"count": 0}

    def count_query(*args, **kwargs):
        query_counter["count"] += 1

    event.listen(engine, "before_cursor_execute", count_query)

    try:
        start = time.perf_counter()

        reports = db.scalars(
            select(VulnerabilityReport)
            .options(
                selectinload(
                    VulnerabilityReport.advisories
                )
            )
            .where(
                VulnerabilityReport.package_name.like(
                    "hw4-n1-package-%"
                )
            )
            .order_by(VulnerabilityReport.id)
            .limit(page_size)
        ).all()

        advisory_count = sum(
            len(report.advisories)
            for report in reports
        )

        elapsed_ms = (time.perf_counter() - start) * 1000

        return (
            elapsed_ms,
            query_counter["count"],
            advisory_count,
        )

    finally:
        event.remove(engine, "before_cursor_execute", count_query)
        db.close()


def percentile(values: list[float], percentage: float) -> float:
    sorted_values = sorted(values)
    position = int(round((percentage / 100) * len(sorted_values))) - 1
    position = max(0, min(position, len(sorted_values) - 1))
    return sorted_values[position]


def summarize(values: list[float]) -> dict:
    return {
        "count": len(values),
        "mean_ms": round(statistics.mean(values), 4),
        "p50_ms": round(percentile(values, 50), 4),
        "p95_ms": round(percentile(values, 95), 4),
        "p99_ms": round(percentile(values, 99), 4),
        "min_ms": round(min(values), 4),
        "max_ms": round(max(values), 4),
    }


def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    rows = []
    summary = {
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "runs_per_condition": RUNS,
        "warmups_per_condition": WARMUPS,
        "page_sizes": PAGE_SIZES,
        "conditions": {},
    }

    for page_size in PAGE_SIZES:
        for variant, function in [
            ("naive", run_naive),
            ("fixed", run_fixed),
        ]:
            for _ in range(WARMUPS):
                function(page_size)

            latencies = []
            query_counts = []
            advisory_counts = []

            for run_number in range(1, RUNS + 1):
                latency_ms, query_count, advisory_count = (
                    function(page_size)
                )

                latencies.append(latency_ms)
                query_counts.append(query_count)
                advisory_counts.append(advisory_count)

                rows.append(
                    {
                        "variant": variant,
                        "page_size": page_size,
                        "run": run_number,
                        "latency_ms": round(latency_ms, 4),
                        "query_count": query_count,
                        "advisory_count": advisory_count,
                    }
                )

            key = f"{variant}_page_{page_size}"

            summary["conditions"][key] = {
                "variant": variant,
                "page_size": page_size,
                "latency": summarize(latencies),
                "query_count": {
                    "min": min(query_counts),
                    "max": max(query_counts),
                    "mean": statistics.mean(query_counts),
                },
                "advisory_count": {
                    "min": min(advisory_counts),
                    "max": max(advisory_counts),
                },
            }

    with open(CSV_PATH, "w", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "variant",
                "page_size",
                "run",
                "latency_ms",
                "query_count",
                "advisory_count",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    with open(JSON_PATH, "w") as file:
        json.dump(summary, file, indent=2)

    print(f"Wrote raw benchmark rows to {CSV_PATH}")
    print(f"Wrote benchmark summary to {JSON_PATH}")

    for key, result in summary["conditions"].items():
        print(
            key,
            "p50=",
            result["latency"]["p50_ms"],
            "p95=",
            result["latency"]["p95_ms"],
            "p99=",
            result["latency"]["p99_ms"],
            "queries=",
            result["query_count"]["min"],
            "-",
            result["query_count"]["max"],
        )


if __name__ == "__main__":
    main()