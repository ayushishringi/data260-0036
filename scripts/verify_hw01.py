#!/usr/bin/env python3
"""Self-check for DATA-260 HW1. Writes reports/hw01/verification.json."""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SID4 = "0036"
EXPECTED = {
    "SID4": SID4,
    "PORT_BASE": 8000 + (int(SID4) % 900),
    "PREFIX": f"s{SID4}",
    "SEED": SID4,
    "VERIFY_SEED": 260000 + int(SID4),
    "DOMAIN_ID": int(SID4) % 8,
    "assigned_domain": "Open-source package vulnerabilities",
}


def exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def ollama_ok() -> tuple[bool, str]:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=3) as resp:
            body = json.loads(resp.read().decode())
        names = [m.get("name") for m in body.get("models", [])]
        return True, ", ".join(names)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def main() -> int:
    ollama_up, ollama_detail = ollama_ok()
    required_files = [
        "index.html",
        "app.js",
        "styles.css",
        "DOMAIN_SCHEMA.md",
        "AGENT.md",
        "agents_demo.py",
        "hw1_client.py",
        "src/model_client.py",
        "Dockerfile",
        "docker-compose.yml",
        "Makefile",
        "README.md",
        "reports/hw01/cases/nondeterminism_input.json",
        "reports/hw01/AI_USE.md",
        "reports/hw01/METRICS.md",
    ]
    file_checks = {path: exists(path) for path in required_files}
    title_ok = "HW1-Ayushi Shringi" in (ROOT / "index.html").read_text()
    h1_ok = "<h1>Vulnerability Report</h1>" in (ROOT / "index.html").read_text()
    schema_ok = "open-source package vulnerabilities" in (ROOT / "DOMAIN_SCHEMA.md").read_text().lower()

    checks = {
        "python_version": sys.version.split()[0],
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "config": EXPECTED,
        "files": file_checks,
        "html_title": title_ok,
        "h1_entity": h1_ok,
        "schema_matches_domain": schema_ok,
        "localhost_port_open": port_open(EXPECTED["PORT_BASE"]),
        "ollama_reachable": ollama_up,
        "ollama_models": ollama_detail,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    failed_files = [p for p, ok in file_checks.items() if not ok]
    passed = title_ok and h1_ok and schema_ok and not failed_files
    report = {"passed": passed, "failed_files": failed_files, "checks": checks}
    out = ROOT / "reports/hw01/verification.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
