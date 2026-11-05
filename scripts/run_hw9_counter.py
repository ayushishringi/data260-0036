"""HW9 Part 1: view counter demo (Redis INCR on every access, MySQL sync every 10).

Usage: make counter-hw09            (25 accesses of the log4j-core report, VULN-0036-HW9-01)
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import socket
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from backend.database import engine  # noqa: E402
from src.redis_store import ReportCache, views_key  # noqa: E402

OUTPUT = ROOT / "reports" / "hw09" / "raw" / "part1_counter.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-code", default="VULN-0036-HW9-01")
    parser.add_argument("--accesses", type=int, default=25)
    args = parser.parse_args()
    # Collect the method's log messages and print them after the access line they belong to.
    messages: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: messages.append(record.getMessage())  # type: ignore[method-assign]
    logging.getLogger("s0036.hw9").addHandler(handler)
    logging.getLogger("s0036.hw9").setLevel(logging.INFO)

    with engine.connect() as conn:
        row = conn.execute(text("SELECT id, package_name FROM vulnerability_reports WHERE report_code = :c"),
                           {"c": args.report_code}).first()
    if row is None:
        raise SystemExit(f"{args.report_code} not found; run make migrate-hw09 first")
    cache = ReportCache()
    cache.reset_report_views(row.id)  # start the demo from zero
    print(f"user={getpass.getuser()} host={socket.gethostname()} time={datetime.now().isoformat(timespec='seconds')}")
    print(f"report id={row.id} ({row.package_name}, {args.report_code})  redis key={views_key(row.id)}")
    print("\n=== Testing Counter ===\n")
    counts, db_after = [], []
    for access in range(1, args.accesses + 1):
        total = cache.increment_report_views(row.id)
        print(f"Access #{access}: Total = {total}")
        for message in messages:
            print(message)
        messages.clear()
        counts.append(total)
        db_after.append(cache.database_view_count(row.id))
    redis_value = int(cache.redis_client.get(views_key(row.id)))
    db_value = cache.database_view_count(row.id)
    print(f"\nRedis {views_key(row.id)} = {redis_value}; MySQL vulnerability_reports.view_count = {db_value}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"report_id": row.id, "report_code": args.report_code, "key": views_key(row.id),
                                  "counts": counts, "db_view_count_after_each_access": db_after,
                                  "final_redis": redis_value, "final_db": db_value,
                                  "ran_at": datetime.now().isoformat(timespec="seconds")}, indent=2) + "\n")


if __name__ == "__main__":
    main()
