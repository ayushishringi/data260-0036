"""HW9 database setup for s0036_rel (safe to run more than once).

1. Adds vulnerability_reports.view_count (Part 1: the Redis counter is synced into it every 10 views).
2. Upserts one vulnerability_reports row per package in data/hw9/reference_facts.json
   (report_code VULN-0036-HW9-NN). These are the records the HW9 answers depend on (Part 3.5)
   and the advisory database the Part 4 Answering Agent can look up. Re-running restores
   every HW9 row to the reference values, which undoes the Part 3.5 stale-data update.

Usage: make migrate-hw09
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect, text  # noqa: E402

from backend.database import engine  # noqa: E402

FACTS = ROOT / "data" / "hw9" / "reference_facts.json"


def description(fact: dict) -> str:
    """Text stored in the description column for one reference fact."""

    return f"{fact['cve']}: {fact['summary']} Fixed in {fact['fixed_version']}."


def main() -> None:
    columns = {c["name"] for c in inspect(engine).get_columns("vulnerability_reports")}
    with engine.begin() as conn:
        if "view_count" not in columns:
            conn.execute(text("ALTER TABLE vulnerability_reports ADD COLUMN view_count INT NOT NULL DEFAULT 0"))
            print("added column vulnerability_reports.view_count")
        else:
            print("column vulnerability_reports.view_count already exists")

        inserted = restored = unchanged = 0
        for fact in json.loads(FACTS.read_text())["facts"]:
            values = {"code": fact["report_code"], "pkg": fact["package"], "ver": fact["affected_versions"],
                      "sev": fact["severity"], "desc": description(fact)}
            row = conn.execute(text("SELECT id, package_name, affected_version, severity, description "
                                    "FROM vulnerability_reports WHERE report_code = :code"), values).first()
            if row is None:
                conn.execute(text(
                    "INSERT INTO vulnerability_reports (report_code, package_name, affected_version, submitter_email,"
                    " description, severity, agreed_to_terms, submission_date, available_count, view_count)"
                    " VALUES (:code, :pkg, :ver, 'hw9-seed@example.edu', :desc, :sev, 1, :now, 1, 0)"),
                    {**values, "now": datetime.now()})
                inserted += 1
            elif (row.package_name, row.affected_version, row.severity, row.description) != (
                    values["pkg"], values["ver"], values["sev"], values["desc"]):
                conn.execute(text("UPDATE vulnerability_reports SET package_name = :pkg, affected_version = :ver, "
                                  "severity = :sev, description = :desc WHERE report_code = :code"), values)
                restored += 1
            else:
                unchanged += 1
    print(f"HW9 advisory rows: inserted={inserted} restored={restored} unchanged={unchanged}")


if __name__ == "__main__":
    main()
