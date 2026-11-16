"""HW10 Part 3.1: freeze 20 Writer drafts from the s0036 pipeline into eval_cases.json.

Runs Planner/Writer/Reviewer (grounded Writer, no evaluator, tracing off, no cache) on 20 questions
chosen to produce drafts of different quality: grounded package questions, packages that are NOT in the
advisory database, general practice questions, and vague questions. For each correlation_id it keeps the
plan (s0036_tasks) and the draft (s0036_drafts) messages exactly as sent.

Writes eval_cases.json and an empty human_labels.csv at the repo root. Label every draft by hand
(make label-hw10), then COMMIT both files before running make judge-hw10 (the judge refuses otherwise).

Usage: make cases-hw10
"""

from __future__ import annotations

import csv
import getpass
import json
import os
import socket
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HW8_LOG_DIR", str(ROOT / "reports" / "hw10" / "logs"))

from src.hw10_pipeline import TracedPipelineClient, hw10_stack  # noqa: E402

CASES_FILE = ROOT / "eval_cases.json"
LABELS_FILE = ROOT / "human_labels.csv"
QUESTIONS = [
    ("grounded", "Which version of minimist fixes the prototype pollution bug?"),
    ("grounded", "Is pyyaml 5.3 safe to use with full_load on untrusted input?"),
    ("grounded", "What severity is CVE-2023-50447 in pillow and which version fixes it?"),
    ("grounded", "Does express 4.18.2 have the open redirect vulnerability?"),
    ("grounded", "Which tar versions are affected by the symbolic-link poisoning issue?"),
    ("grounded", "How should I fix the axios XSRF-TOKEN disclosure in my frontend?"),
    ("grounded", "Is moment 2.29.4 still vulnerable to the RFC 2822 ReDoS?"),
    ("grounded", "What is CVE-2024-22195 in jinja2 and how bad is it?"),
    ("not in database", "Which version of openssl fixes Heartbleed?"),
    ("not in database", "Is the npm package event-stream still compromised?"),
    ("not in database", "What CVE affects the Python package cryptography 3.2?"),
    ("not in database", "Which spring-core version fixes CVE-2022-22965?"),
    ("not in database", "How do I know if my Go service is affected by the xz backdoor?"),
    ("general", "How do I check which of my npm dependencies have known vulnerabilities?"),
    ("general", "What is the difference between a CVE and a GHSA advisory?"),
    ("general", "Should I pin transitive dependencies in a Python project?"),
    ("general", "What does a CVSS score of 9.8 mean for patch priority?"),
    ("vague", "Is it safe?"),
    ("vague", "lodash"),
    ("vague", "My build broke after upgrading a package, what now?"),
]


def main() -> None:
    if CASES_FILE.exists() and "--force" not in sys.argv:
        raise SystemExit(f"{CASES_FILE.name} already exists; the cases are frozen (use --force to rebuild "
                         "BEFORE labeling and committing only)")
    print(f"user={getpass.getuser()} host={socket.gethostname()} time={datetime.now().isoformat(timespec='seconds')}")
    cases = []
    with hw10_stack(ROOT / "reports" / "hw10" / "raw" / "runs" / "cases", with_evaluator=False, trace=False):
        client = TracedPipelineClient()
        for n, (category, question) in enumerate(QUESTIONS, 1):
            final = client.ask(question)
            cid = final["correlation_id"]
            seen = client.seen.get(cid, {})
            plan_msg, draft_msg = seen.get("plan", {}), seen.get("draft", {})
            cases.append({"case_id": f"E{n:02d}", "category": category, "trace_id": cid, "question": question,
                          "plan": plan_msg.get("plan"), "draft": draft_msg.get("draft"),
                          "grounding_facts": draft_msg.get("facts", []), "written_at": draft_msg.get("written_at"),
                          "review_status": final.get("status")})
            print(f"E{n:02d} {category:<16} words={len((draft_msg.get('draft') or '').split()):>4} "
                  f"status={final.get('status')}  {question}", flush=True)
        client.close()
    CASES_FILE.write_text(json.dumps({
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": "s0036 Writer drafts (s0036_drafts), grounded Writer (HW8_GROUNDED=1), Ollama qwen3:4b",
        "criterion": "Writer Helpfulness: is the draft accurate and useful for the question? 1 = very poor, 5 = excellent",
        "cases": cases}, indent=2) + "\n")
    with LABELS_FILE.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case_id", "trace_id", "helpfulness_label", "notes"])
        for c in cases:
            writer.writerow([c["case_id"], c["trace_id"], "", ""])
    print(f"\nwrote {CASES_FILE.name} ({len(cases)} drafts) and an empty {LABELS_FILE.name}")
    print("next: make label-hw10  ->  git add eval_cases.json human_labels.csv && git commit  ->  make judge-hw10")


if __name__ == "__main__":
    main()
