"""HW10 Part 3.1: hand-label the 20 frozen Writer drafts (helpfulness 1-5) into human_labels.csv.

Shows each case (question, advisory facts, draft) and asks for a label. Already-labeled cases are
skipped, so the script can be stopped and resumed. Labels must come from a person, not a model, and
must not be changed after the judge has been run.

Rubric (same 1-5 scale as the judge):
  1 very poor  wrong, off-topic or harmful; does not answer the question
  2 poor       answers partly, but a major factual error or misses the main point
  3 fair       answers with minor errors, significant omissions, or padding
  4 good       accurate and useful with small issues (verbosity, one missing detail)
  5 excellent  accurate, direct and complete; a practitioner could act on it immediately

Usage: make label-hw10
"""

from __future__ import annotations

import csv
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_FILE = ROOT / "eval_cases.json"
LABELS_FILE = ROOT / "human_labels.csv"


def main() -> None:
    cases = json.loads(CASES_FILE.read_text())["cases"]
    with LABELS_FILE.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    by_id = {r["case_id"]: r for r in rows}
    print(__doc__.split("Usage")[0])
    for case in cases:
        row = by_id[case["case_id"]]
        if row["helpfulness_label"].strip():
            continue
        print("=" * 100)
        print(f"{case['case_id']}  [{case['category']}]  trace_id={case['trace_id']}")
        print(f"QUESTION: {case['question']}")
        for fact in case["grounding_facts"] or ["(no advisory record for this question)"]:
            print(textwrap.fill(f"FACT: {fact}", 100, subsequent_indent="      "))
        print("DRAFT:")
        for para in (case["draft"] or "").split("\n"):
            print(textwrap.fill(para, 100, initial_indent="  ", subsequent_indent="  ") if para.strip() else "")
        while True:
            answer = input("label 1-5 (q = save and quit): ").strip().lower()
            if answer == "q":
                save(rows)
                sys.exit(0)
            if answer in {"1", "2", "3", "4", "5"}:
                row["helpfulness_label"] = answer
                row["notes"] = input("note (optional): ").strip()
                save(rows)
                break
    done = sum(1 for r in rows if r["helpfulness_label"].strip())
    print(f"\n{done}/{len(rows)} labeled. Next: git add eval_cases.json human_labels.csv && git commit, "
          "then make judge-hw10")


def save(rows: list[dict[str, str]]) -> None:
    with LABELS_FILE.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["case_id", "trace_id", "helpfulness_label", "notes"])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
