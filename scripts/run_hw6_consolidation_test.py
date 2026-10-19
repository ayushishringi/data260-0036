"""HW6 Part 4.5: consolidate a 55-line MEMORY.md with duplicates and contradictions.

Writes reports/hw06/raw/MEMORY_original.md, MEMORY_consolidated.md and
consolidation_test.json. Pass --apply to also copy the fixture into the real
MEMORY.md (so /compact can then be run against it through the API).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.hw6_file_memory import (  # noqa: E402
    MEMORY_PATH,
    _content_lines,
    audit_resolutions,
    consolidate_memory_text,
)
from backend.hw6_mongo_database import MONGO_DB_NAME, MONGO_COLLECTION_NAME  # noqa: E402
from src.model_client import DEFAULT_MODEL  # noqa: E402

RAW = ROOT / "reports" / "hw06" / "raw"

# 53 fact lines + 2 header lines = 55 lines.
FIXTURE_FACTS = [
    "[2026-08-25] course: DATA-260",
    "[2026-08-25] sid4: 0036",
    "[2026-09-01] port: 8036",
    "[2026-08-25] domain: open-source package vulnerability tracking (DOMAIN_ID 4)",
    "[2026-09-02] api_framework: FastAPI",
    "[2026-09-02] validation: Pydantic v2 models for every request body",
    "[2026-09-05] ollama_model: llama3.2:3b",
    "[2026-09-10] python_version: 3.12",
    "[2026-09-10] hardware: MacBook Pro, Apple M5 Pro, 24 GB",
    "[2026-10-01] mongo_database: s0036_doc",
    "[2026-10-01] documents_collection: vulnerability_documents",
    "[2026-10-01] memory_collections: messages, summaries, episodes",
    "[2026-10-01] ollama_model: qwen3:4b",
    "[2026-10-02] severity_values: critical, high, medium, low",
    "[2026-10-02] status_values: open, triaged, resolved, ignored",
    "[2026-10-03] short_term_n_default: 8",
    "[2026-10-04] summarize_every_user_msgs: 3",
    "[2026-10-05] episodic_top_k: 3",
    "[2026-10-05] embedding_model: all-MiniLM-L6-v2 with a hash-vector fallback",
    "[2026-10-06] ollama_num_ctx: 16384",
    "[2026-10-06] ollama_seed: 36",
    "[2026-10-07] input_price: $1 per million tokens",
    "[2026-10-07] output_price: $5 per million tokens",
    "[2026-10-08] collaborators: Sbnikitha, supriyaselvanganesan",
    "[2026-10-08] submission_tag: hw6",
    "[2026-10-08] report_file: Shringi_HW6.pdf",
    "[2026-10-09] test_runner: unittest (pytest is not installed in .venv)",
    "[2026-10-09] lifetime_summary_every: 2 session summaries",
    "[2026-10-10] The user prefers short, numbered answers in reports.",
    "[2026-10-10] Raw experiment output always goes under reports/hw06/raw/.",
    "[2026-10-14] port: 8000",
    "[2026-10-15] short_term_n_default: 12",
    "[2026-10-15] summarize_every_user_msgs: 5",
    "[2026-10-16] memory_policy_options: window, compressed_window",
    "[2026-10-16] api_framework: fastapi",
    "[2026-10-16] course: DATA-260",
    "[2026-10-16] mongo_database: s0036_doc",
    "[2026-10-17] The user prefers short, numbered answers in reports.",
    "[2026-10-17] ollama_model: qwen3:4b",
    "[2026-10-17] episodic_top_k: 3",
    "[2026-10-17] course: data-260",
    "[2026-10-17] Raw experiment output always goes under reports/hw06/raw/",
    "[2026-10-17] api_framework: FastAPI",
    "[2026-10-17] sid4: 0036",
    "[2026-10-17] input_price: $1 per million tokens",
    "[2026-10-17] output_price: $5 per million tokens",
    "[2026-10-17] collaborators: Sbnikitha, supriyaselvanganesan",
    "[2026-10-17] memory_collections: messages, summaries, episodes",
    "[2026-10-18] severity_values: critical, high, medium, low",
    "[2026-10-18] status_values: open, triaged, resolved, ignored",
    "[2026-10-18] ollama_num_ctx: 16384",
    "[2026-10-18] hardware: MacBook Pro, Apple M5 Pro, 24 GB",
    "[2026-10-18] submission_tag: hw6",
]


def build_fixture() -> str:
    header = ["# Durable Memory", "<!-- consolidated_at: 2026-10-10T09:00:00+00:00 -->"]
    return "\n".join(header + [f"- {fact}" for fact in FIXTURE_FACTS]) + "\n"


def ground_truth() -> dict[str, str]:
    """Authoritative values taken from project configuration, not from memory."""

    service = (ROOT / "backend" / "hw6_memory_service.py").read_text(encoding="utf-8")
    return {
        "port": "8036",  # PORT_BASE = 8000 + (36 mod 900); Makefile PORT ?= 8036
        "ollama_model": DEFAULT_MODEL,
        "mongo_database": MONGO_DB_NAME,
        "documents_collection": MONGO_COLLECTION_NAME,
        "short_term_n_default": "12" if 'getenv("SHORT_TERM_N", "12")' in service else "?",
        "summarize_every_user_msgs": "5" if 'getenv("SUMMARIZE_EVERY_USER_MSGS", "5")' in service else "?",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="copy the fixture into MEMORY.md")
    args = parser.parse_args()

    original = build_fixture()
    consolidated, stats = consolidate_memory_text(original)
    incorrect = audit_resolutions(stats["resolutions"], ground_truth())

    original_values = {line.split("] ", 1)[-1].casefold().rstrip(".") for line in _content_lines(original)}
    consolidated_text = consolidated.casefold()
    missing = sorted(value for value in original_values if value.split(": ", 1)[-1] not in consolidated_text)

    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "MEMORY_original.md").write_text(original, encoding="utf-8")
    (RAW / "MEMORY_consolidated.md").write_text(consolidated, encoding="utf-8")
    result = {
        "original_file_lines": len(original.splitlines()),
        "consolidated_file_lines": len(consolidated.splitlines()),
        "memory_lines_before": stats["before"],
        "memory_lines_after": stats["after"],
        "duplicates_merged": stats["duplicates_merged"],
        "contradictions_resolved": stats["contradictions_resolved"],
        "resolutions": stats["resolutions"],
        "incorrectly_resolved": incorrect,
        "values_missing_after_consolidation": missing,
        "no_silent_drop": not missing,
        "under_40_lines": len(consolidated.splitlines()) < 40,
    }
    (RAW / "consolidation_test.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.apply:
        MEMORY_PATH.write_text(original, encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
