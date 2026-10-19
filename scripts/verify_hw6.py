"""Smoke test for DATA-260 HW6; writes reports/hw06/verification.json.

Starts the FastAPI app on PORT_BASE (or reuses one already running there) and
checks behaviour, not wording: document CRUD + validation, /api/chat memory
fields, /api/memory, /api/aggregate, file-memory commands that do not modify
MEMORY.md, consolidation on an in-memory fixture, and the AGENT.md rule check.
The only data it creates is one temporary document (deleted again) and one
short chat session under a verify-* user id.

Usage: make verify-hw06
"""

from __future__ import annotations

import json
import os
import random
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "reports" / "hw06" / "verification.json"
SID4 = "0036"
PORT_BASE = 8000 + (int(SID4) % 900)
SEED = int(SID4)
VERIFY_SEED = 260000 + int(SID4)
BASE_URL = f"http://127.0.0.1:{PORT_BASE}"


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip()


def request(method: str, path: str, body: dict | None = None, timeout: int = 300) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE_URL + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        return exc.code, json.loads(raw) if raw else None


def ensure_server() -> subprocess.Popen | None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", PORT_BASE)) == 0:
            return None
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(PORT_BASE)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            if request("GET", "/api/health", timeout=2)[0] == 200:
                return process
        except OSError:
            time.sleep(1)
    process.terminate()
    raise SystemExit(f"API did not start on port {PORT_BASE}")


def check(checks: list[dict], name: str, passed: bool, detail: object = None) -> None:
    checks.append({"check": name, "passed": bool(passed), "detail": detail})
    print(f"{'PASS' if passed else 'FAIL'}  {name}", flush=True)


def main() -> int:
    checks: list[dict] = []
    rng = random.Random(VERIFY_SEED)
    user_id = f"verify-hw06-{VERIFY_SEED}-{rng.randrange(10**6):06d}-{int(time.time())}"
    process = ensure_server()
    try:
        status, body = request("GET", "/api/health")
        check(checks, f"backend responds on PORT_BASE {PORT_BASE}", status == 200, body)

        document = {
            "title": f"verify-hw06 {user_id}", "severity": "high",
            "status": "open", "discovered_at": "2026-10-16T12:00:00Z",
        }
        status, created = request("POST", "/api/documents", document)
        check(checks, "POST /api/documents creates a record (201)", status == 201 and "id" in created)
        doc_id = created.get("id", "missing") if isinstance(created, dict) else "missing"
        status, fetched = request("GET", f"/api/documents/{doc_id}")
        check(checks, "GET /api/documents/{id} returns it (200)", status == 200 and fetched.get("id") == doc_id)
        status, _ = request("GET", "/api/documents")
        check(checks, "GET /api/documents lists records (200)", status == 200)
        status, updated = request("PUT", f"/api/documents/{doc_id}", {**document, "status": "triaged"})
        check(checks, "PUT /api/documents/{id} updates it (200)", status == 200 and updated.get("status") == "triaged")
        status, _ = request("DELETE", f"/api/documents/{doc_id}")
        check(checks, "DELETE /api/documents/{id} removes it (204)", status == 204)
        status, _ = request("GET", f"/api/documents/{doc_id}")
        check(checks, "deleted record returns 404", status == 404)
        status, _ = request("POST", "/api/documents", {k: v for k, v in document.items() if k != "title"})
        check(checks, "missing required field rejected (422)", status == 422)
        status, _ = request("POST", "/api/documents", {**document, "severity": "urgent"})
        check(checks, "invalid enum rejected (422)", status == 422)
        status, _ = request("POST", "/api/documents", {**document, "title": 123, "discovered_at": "not-a-date"})
        check(checks, "wrong data types rejected (422)", status == 422)

        session_id = "verify-session"
        status, chat = request("POST", "/api/chat", {
            "user_id": user_id, "session_id": session_id,
            "message": "My verification package is left-pad-plus 3.4.1.",
        })
        check(checks, "POST /api/chat returns a non-empty reply", status == 200 and bool(chat.get("reply", "").strip()))
        used = chat.get("used", {}) if isinstance(chat, dict) else {}
        usage = chat.get("usage", {}) if isinstance(chat, dict) else {}
        check(checks, "chat response shows memory used",
              {"short_term_message_count", "short_term_messages", "long_term_summary", "episodic_facts"} <= set(used))
        check(checks, "chat response logs token usage", usage.get("prompt_tokens", 0) > 0
              and "short_term_window" in usage.get("component_token_estimates", {}), usage.get("config"))
        status, chat2 = request("POST", "/api/chat", {
            "user_id": user_id, "session_id": session_id, "message": "Which package am I verifying?",
        })
        facts = [item["fact"] for item in chat2.get("used", {}).get("episodic_facts", [])]
        check(checks, "episodic fact from turn 1 retrieved on turn 2", any("left-pad-plus" in fact for fact in facts), facts)

        status, memory = request("GET", f"/api/memory/{user_id}")
        check(checks, "GET /api/memory/{user_id} returns messages and episodes",
              status == 200 and len(memory.get("messages", [])) >= 4 and len(memory.get("episodes", [])) >= 1)
        status, aggregate = request("GET", f"/api/aggregate/{user_id}")
        counts = aggregate.get("daily_message_counts", []) if isinstance(aggregate, dict) else []
        check(checks, "GET /api/aggregate/{user_id} returns daily counts",
              status == 200 and sum(row["count"] for row in counts) >= 4, counts)

        status, help_body = request("POST", "/api/chat", {"user_id": user_id, "session_id": session_id, "message": "/help"})
        reply = help_body.get("reply", "") if isinstance(help_body, dict) else ""
        check(checks, "/help lists all four commands", all(cmd in reply for cmd in ("/memory", "/compact", "/dream", "/help")))
        status, mem_body = request("POST", "/api/chat", {"user_id": user_id, "session_id": session_id, "message": "/memory"})
        file_memory = mem_body.get("file_memory", {}) if isinstance(mem_body, dict) else {}
        check(checks, "/memory returns AGENT.md, MEMORY.md and consolidation status",
              "## Prohibited actions" in file_memory.get("agent", "") and "consolidation_required" in file_memory)
    finally:
        if process is not None:
            process.terminate()

    from backend.hw6_file_memory import audit_resolutions, consolidate_memory_text
    from scripts.run_hw6_consolidation_test import build_fixture, ground_truth

    fixture = build_fixture()
    consolidated, stats = consolidate_memory_text(fixture)
    check(checks, "55-line fixture consolidates to < 40 lines",
          len(fixture.splitlines()) == 55 and len(consolidated.splitlines()) < 40,
          [len(fixture.splitlines()), len(consolidated.splitlines())])
    check(checks, ">= 3 duplicates merged and >= 3 contradictions resolved",
          stats["duplicates_merged"] >= 3 and stats["contradictions_resolved"] >= 3,
          [stats["duplicates_merged"], stats["contradictions_resolved"]])
    check(checks, "superseded values are kept, not silently deleted",
          all(f'"{loser["value"]}"' in consolidated for item in stats["resolutions"] for loser in item["superseded"]))
    check(checks, "audit identifies the incorrectly resolved contradiction",
          audit_resolutions(stats["resolutions"], ground_truth()) == [{"key": "port", "kept": "8000", "expected": "8036"}])

    rules = subprocess.run([sys.executable, "scripts/check_agent_rules.py"], cwd=ROOT, capture_output=True, text=True)
    check(checks, "generated function follows AGENT.md (check_agent_rules.py)", rules.returncode == 0)

    probes = yaml.safe_load((ROOT / "memory_probes.yaml").read_text(encoding="utf-8"))
    check(checks, "memory_probes.yaml has 5 probes with criteria and a 1-5 rubric",
          len(probes["probes"]) == 5 and set(probes["rubric"]) == {1, 2, 3, 4, 5})
    comparison = json.loads((ROOT / "reports/hw06/raw/memory_cost_comparison.json").read_text(encoding="utf-8"))
    settings = sorted(item["setting"] for item in comparison["settings"])
    check(checks, "Part 3 results cover N=4/12/30 and the compression policy",
          settings == sorted(["N=4,window", "N=12,window", "N=30,window", "N=12,compressed_window"]), settings)

    result = {
        "homework": 6,
        "SID4": SID4,
        "PORT_BASE": PORT_BASE,
        "PREFIX": f"s{SID4}",
        "SEED": SEED,
        "VERIFY_SEED": VERIFY_SEED,
        "DOMAIN_ID": int(SID4) % 8,
        "commit": git("rev-parse", "HEAD") or "uncommitted",
        "tag_hw6_commit": git("rev-parse", "hw6^{commit}") or "missing",
        "working_tree_clean": git("status", "--porcelain", "--", "backend", "src", "scripts") == "",
        "model": os.getenv("OLLAMA_MODEL", "qwen3:4b") + " via local Ollama",
        "configuration": {
            "OLLAMA_NUM_CTX": int(os.getenv("OLLAMA_NUM_CTX", "16384")),
            "OLLAMA_SEED": int(os.getenv("OLLAMA_SEED", str(SEED))),
            "SHORT_TERM_N": int(os.getenv("SHORT_TERM_N", "12")),
            "MEMORY_POLICY": os.getenv("MEMORY_POLICY", "window"),
        },
        "verified_user_id": user_id,
        "checks": checks,
        "passed": all(item["passed"] for item in checks),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{sum(item['passed'] for item in checks)}/{len(checks)} checks passed -> {OUTPUT}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
