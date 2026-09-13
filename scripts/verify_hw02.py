#!/usr/bin/env python3

from __future__ import annotations

import json
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

SID4 = "0036"
PORT_BASE = 8036
PREFIX = "s0036"
SEED = 36
VERIFY_SEED = 260036
DOMAIN_ID = 4
MODEL = "qwen3:4b"


class FakeClient:
    """Deterministic client used only for graph smoke testing."""

    def complete(self, messages, temperature=0.2, format=None):
        properties = (format or {}).get("properties", {})

        if "approved" in properties:
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "approved": True,
                        "feedback": "Smoke-test proposal approved.",
                    }
                )
            )

        return SimpleNamespace(
            text=json.dumps(
                {
                    "tags": [
                        "security issue",
                        "certificate check",
                        "network attack",
                    ],
                    "summary": (
                        "A certificate validation issue may expose "
                        "encrypted network traffic."
                    ),
                }
            )
        )


def file_exists(relative_path: str) -> bool:
    return (ROOT / relative_path).exists()


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def api_health_check() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{PORT_BASE}/api/health",
            timeout=3,
        ) as response:
            body = json.loads(response.read().decode())

        passed = body.get("status") == "ok"
        return passed, json.dumps(body)

    except Exception as exc:
        return False, str(exc)


def graph_smoke_test() -> tuple[bool, dict]:
    from agents_graph import build_graph

    graph = build_graph()

    initial_state = {
        "title": "Smoke-test vulnerability",
        "content": (
            "A package vulnerability may expose encrypted traffic "
            "when certificate validation is bypassed."
        ),
        "llm": FakeClient(),
        "turn_ceiling": 10,
        "turn_count": 0,
        "planner_attempts": 0,
        "planner_proposal": {},
        "reviewer_feedback": {},
        "validation_error": "",
        "status": "running",
    }

    final_state = graph.invoke(initial_state)

    proposal = final_state.get("planner_proposal", {})
    tags = proposal.get("tags", [])
    summary = proposal.get("summary", "")

    passed = (
        final_state.get("status") == "completed"
        and len(tags) == 3
        and all(isinstance(tag, str) for tag in tags)
        and isinstance(summary, str)
        and len(summary.split()) <= 25
        and final_state.get("turn_count", 0) <= 10
    )

    details = {
        "status": final_state.get("status"),
        "turn_count": final_state.get("turn_count"),
        "planner_attempts": final_state.get("planner_attempts"),
        "tag_count": len(tags),
        "summary_word_count": len(summary.split()),
    }

    return passed, details


def main() -> int:
    required_files = [
        "index.html",
        "app.js",
        "styles.css",
        "requirements.txt",
        "backend/main.py",
        "agents_graph.py",
        "scripts/run_hw02_experiments.py",
        "scripts/verify_hw02.py",
        "reports/hw02/RUN_LOG.txt",
        "reports/hw02/METRICS.md",
        "reports/hw02/AI_USE.md",
        "reports/hw02/cases/schema_input.json",
        "reports/hw02/cases/adversarial_input.json",
        "reports/hw02/raw/schema_30_runs_metrics.json",
        "reports/hw02/raw/ceiling_2_20_runs_metrics.json",
        "reports/hw02/raw/ceiling_10_20_runs_metrics.json",
        "reports/hw02/raw/adversarial_5_runs_metrics.json",
    ]

    file_results = {
        path: file_exists(path)
        for path in required_files
    }

    health_passed, health_details = api_health_check()
    graph_passed, graph_details = graph_smoke_test()

    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except Exception:
        commit_hash = "unavailable"

    checks = {
        "required_files": file_results,
        "port_open": port_open(PORT_BASE),
        "api_health": {
            "passed": health_passed,
            "details": health_details,
        },
        "langgraph_smoke_test": {
            "passed": graph_passed,
            "details": graph_details,
        },
    }

    failed_files = [
        path for path, passed in file_results.items() if not passed
    ]

    passed = not failed_files and health_passed and graph_passed

    report = {
        "passed": passed,
        "homework": "DATA-260 HW2",
        "SID4": SID4,
        "PORT_BASE": PORT_BASE,
        "PREFIX": PREFIX,
        "SEED": SEED,
        "VERIFY_SEED": VERIFY_SEED,
        "DOMAIN_ID": DOMAIN_ID,
        "model": MODEL,
        "commit_hash": commit_hash,
        "checks": checks,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }

    output_path = ROOT / "reports/hw02/verification.json"
    output_path.write_text(json.dumps(report, indent=2) + "\n")

    print(json.dumps(report, indent=2))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())