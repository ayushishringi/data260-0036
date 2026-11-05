"""HW9: read the HW9 advisory rows of s0036_rel.vulnerability_reports.

Used by the grounded HW8 Writer (answers cite the record), by the semantic cache (the data-version
marker of a cached answer), and by the Part 4 Answering Agent when a lesson tells it to look up.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy import text

HW9_CODE_PATTERN = "VULN-0036-HW9-%"
FIELDS = "id, report_code, package_name, affected_version, severity, description, updated_at"


def _engine() -> Any:
    from backend.database import engine
    return engine


def all_records() -> list[dict[str, Any]]:
    """Every HW9 advisory row, longest package name first (so 'log4j-core' wins over shorter names)."""

    with _engine().connect() as conn:
        rows = conn.execute(text(f"SELECT {FIELDS} FROM vulnerability_reports WHERE report_code LIKE :p"),
                            {"p": HW9_CODE_PATTERN}).mappings().all()
    return sorted((dict(r) for r in rows), key=lambda r: -len(r["package_name"]))


def mentions(question: str, package: str) -> bool:
    """True if the package name appears in the question as a whole word (case-insensitive)."""

    return re.search(rf"(?<![\w./-]){re.escape(package)}(?![\w-])", question, re.IGNORECASE) is not None


def find_records(question: str) -> list[dict[str, Any]]:
    """Advisory rows for the packages named in a question."""

    return [r for r in all_records() if mentions(question, r["package_name"])]


def records_by_id(record_ids: list[int]) -> list[dict[str, Any]]:
    """Current rows for the given ids (missing ids are left out)."""

    if not record_ids:
        return []
    marks = ", ".join(f":i{n}" for n in range(len(record_ids)))
    with _engine().connect() as conn:
        rows = conn.execute(text(f"SELECT {FIELDS} FROM vulnerability_reports WHERE id IN ({marks})"),
                            {f"i{n}": v for n, v in enumerate(record_ids)}).mappings().all()
    return [dict(r) for r in rows]


def data_version(records: list[dict[str, Any]]) -> str:
    """Data-version marker: hash of the content and updated_at of the records an answer used."""

    if not records:
        return "none"
    parts = [f"{r['id']}|{r['affected_version']}|{r['severity']}|{r['description']}|{r['updated_at']}"
             for r in sorted(records, key=lambda r: r["id"])]
    return "v-" + hashlib.sha1("\n".join(parts).encode()).hexdigest()[:16]


def current_version(record_ids: list[int]) -> str:
    """Data-version marker computed from the rows as they are in the database right now."""

    return data_version(records_by_id(record_ids))


def fact_line(record: dict[str, Any]) -> str:
    """One-line citation of an advisory record."""

    return (f"{record['report_code']} (s0036_rel id {record['id']}): {record['package_name']} affected "
            f"{record['affected_version']}, severity {record['severity']}. {record['description']}")


def update_record(report_code: str, **fields: str) -> dict[str, Any]:
    """Change affected_version / severity / description of one row; returns the row after the update."""

    allowed = {"affected_version", "severity", "description"}
    if not fields or set(fields) - allowed:
        raise ValueError(f"can only update {sorted(allowed)}")
    sets = ", ".join(f"{name} = :{name}" for name in fields)
    with _engine().begin() as conn:
        conn.execute(text(f"UPDATE vulnerability_reports SET {sets}, updated_at = NOW() WHERE report_code = :code"),
                     {**fields, "code": report_code})
        row = conn.execute(text(f"SELECT {FIELDS} FROM vulnerability_reports WHERE report_code = :code"),
                           {"code": report_code}).mappings().first()
    if row is None:
        raise LookupError(report_code)
    return dict(row)
