"""Smoke test for DATA-260 HW7; writes reports/hw07/verification.json.

Starts the API on PORT_BASE (or reuses one already running there) and checks behavior,
not wording: JWT login/me and role rules, the hand-written agent loop completing a
verification task, error recovery, the Reflexion verifier, the MRKL tools and their
defenses, the bash safety gate, and that the raw experiment files exist and are consistent.
It creates one temporary report (deleted again) and a temporary sandbox; it never edits
application code.

Usage: make verify-hw07   (add SKIP_MODEL=1 to skip the one live model check)
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hw5_tools.domain import DomainStore, execute_tool  # noqa: E402
from src import file_tools  # noqa: E402
from src.bikeshare_tools import TripTable, calculator, csv_sql, fetch_snapshot, policy_retriever  # noqa: E402

RAW = ROOT / "reports" / "hw07" / "raw"
OUTPUT = ROOT / "reports" / "hw07" / "verification.json"
SID4 = "0036"
PORT_BASE = 8000 + int(SID4) % 900
SEED = int(SID4)
VERIFY_SEED = 260000 + int(SID4)
BASE = f"http://127.0.0.1:{PORT_BASE}"
PASSWORDS = {"reader": "reader-pass-0036", "writer": "writer-pass-0036", "moderator": "moderator-pass-0036"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def http(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, object]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(BASE + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode()
            is_json = "json" in response.headers.get("Content-Type", "")
            return response.status, (json.loads(raw) if raw else None) if is_json else raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        return exc.code, json.loads(raw) if raw else None


def ensure_server() -> subprocess.Popen | None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", PORT_BASE))
        except OSError:
            return None  # already running
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1",
                                "--port", str(PORT_BASE)], cwd=ROOT, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            status, body = http("GET", "/api/health")
            if status == 200 and isinstance(body, dict) and body.get("status") == "ok":
                return process
        except (OSError, ValueError):
            pass
        time.sleep(1)
    process.terminate()
    raise SystemExit(f"API did not start on {PORT_BASE}")


def main() -> int:
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: object = None) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        print(f"{'PASS' if passed else 'FAIL'}  {name}", flush=True)

    process = ensure_server()
    try:
        # ---- Part 1: JWT + roles
        status, body = http("POST", "/auth/login", {"username": "writer0036", "password": PASSWORDS["writer"]})
        check("POST /auth/login valid credentials -> 200 + JWT", status == 200 and isinstance(body, dict)
              and str(body.get("access_token", "")).count(".") == 2)
        status, _ = http("POST", "/auth/login", {"username": "writer0036", "password": "wrong"})
        check("POST /auth/login invalid credentials -> 401", status == 401)
        tokens = {r: http("POST", "/auth/login", {"username": f"{r}0036", "password": p})[1]["access_token"]
                  for r, p in PASSWORDS.items()}
        check("GET /auth/me without token -> 401", http("GET", "/auth/me")[0] == 401)
        check("GET /auth/me invalid token -> 401", http("GET", "/auth/me", token="not.a.jwt")[0] == 401)
        status, me = http("GET", "/auth/me", token=tokens["reader"])
        check("GET /auth/me valid token -> identity + role", status == 200 and me.get("role") == "reader")
        status, _ = http("GET", "/api/reports", token=tokens["reader"])
        check("GET /api/reports as reader -> 200", status == 200)
        report = {"packageName": f"verify-hw07-{VERIFY_SEED}", "affectedVersion": "<1.0",
                  "submitterEmail": "verify@example.edu", "severity": "low", "agreedToTerms": True,
                  "description": "Temporary record created by verify_hw7.py and deleted again."}
        check("POST /api/reports as reader -> 403", http("POST", "/api/reports", report, tokens["reader"])[0] == 403)
        status, created = http("POST", "/api/reports", report, tokens["writer"])
        check("POST /api/reports as writer -> 201", status == 201)
        report_id = created.get("id") if isinstance(created, dict) else None
        check("DELETE /api/reports/{id} as writer -> 403",
              http("DELETE", f"/api/reports/{report_id}", token=tokens["writer"])[0] == 403)
        check("DELETE /api/reports/{id} as moderator -> 204",
              http("DELETE", f"/api/reports/{report_id}", token=tokens["moderator"])[0] == 204)
        status, _ = http("GET", "/bikeshare")
        check("GET /bikeshare UI page -> 200", status == 200)
    finally:
        if process is not None:
            process.terminate()

    from sqlalchemy import text

    from backend.database import engine
    with engine.connect() as connection:
        hashes = [row[0] for row in connection.execute(text("SELECT password_hash FROM users"))]
    check("MySQL users store only salted hashes", all("$" in h and h not in PASSWORDS.values() for h in hashes),
          f"{len(hashes)} users")

    # ---- Part 2: agent loop (one live model check) + error recovery
    if os.getenv("SKIP_MODEL") != "1":
        from src.agent_loop import run_agent
        from src.reflexion import verify
        case = json.loads((ROOT / "tests/fixtures/hw7/agent_cases.json").read_text())["cases"][0]
        result = run_agent(case["prompt"], run_id="verify-hw07-A", log_path=None, echo=False)
        verdict = verify(case, result)
        check("run_agent completes verification task A with >= 2 tool calls",
              result["stop_reason"] == "final_answer" and result["total_tool_calls"] >= 2,
              {"tools": verdict["tools_called"], "verifier_passed": verdict["passed"]})
    observation = json.loads(execute_tool("detail", {"id": 4242}, DomainStore.hw7_fixture()))
    check("execute_tool on nonexistent id returns a useful error", not observation["ok"]
          and "valid ids" in observation["error"])

    # ---- Part 3/4/5 tools and defenses (no model)
    table = TripTable.from_csv_bytes((ROOT / "tests/fixtures/hw7/bikeshare_payperuse_wins.csv").read_bytes())
    before = table.fingerprint()
    blocked = csv_sql(table, "DELETE FROM trips")
    check("csv_sql rejects non-SELECT and leaves data unchanged", not blocked["success"]
          and table.fingerprint() == before)
    check("calculator evaluates arithmetic and rejects code", calculator("25 * 2 + 1")["data"]["value"] == 51.0
          and not calculator("__import__('os')")["success"])
    hostile = fetch_snapshot((ROOT / "tests/fixtures/hw7/hostile_pricing.html").resolve().as_uri())
    retrieved = policy_retriever(hostile, hostile.url, "single ride unlock fee", 3)
    check("policy_retriever labels retrieved text as untrusted",
          retrieved["success"] and retrieved["data"].get("trust") == "UNTRUSTED_EXTERNAL_DATA")

    # ---- Part 6: safety gate + sandboxed file tools (no model)
    expected = {"ls -la": True, "cat app.py": True, "grep -rn DEBUG .": True, "git status": True,
                "wc -l app.py": True, "rm -rf ./build": False, "sudo chown root:root app.py": False,
                "ls && dd if=/dev/zero of=/dev/disk4 bs=1m": False, "echo pwned >| /etc/hosts": False,
                "mkfs.ext4 /dev/sdb1": False}
    gate = {cmd: file_tools.confirm_bash(cmd)["allowed"] for cmd in expected}
    check("safety gate: 5 commands allowed, 5 destructive blocked", gate == expected,
          [c for c in expected if gate[c] != expected[c]])
    with tempfile.TemporaryDirectory(prefix="verify_hw07_sandbox_") as tmp:
        file_tools.set_sandbox(tmp)
        file_tools.write_file("x.py", "DEBUG = True\n")
        found = file_tools.search_in_files("DEBUG", file_pattern="*.py")["data"]["count"] == 1
        escaped = file_tools.read_file("../../etc/hosts")["ok"]
    check("file tools work in the sandbox and refuse paths outside it", found and not escaped)

    # ---- raw experiment evidence
    rel_csv = RAW / "reliability_attempts.csv"
    rel_rows = list(csv.DictReader(rel_csv.open())) if rel_csv.exists() else []
    check("Part 2 reliability: >= 20 attempts saved in raw/", len(rel_rows) >= 20, len(rel_rows))
    comparison = RAW / "reflexion_comparison.json"
    check("Part 3 original-vs-Reflexion comparison saved", comparison.exists())
    reflections = RAW / "reflections.jsonl"
    check("Part 3 stored reflections include evidence", reflections.exists() and all(
        "evidence" in json.loads(line) for line in reflections.read_text().splitlines() if line.strip()))
    snapshots_ok = True
    for scenario in ("membership_wins", "payperuse_wins"):
        snap = RAW / f"pricing_snapshot_{scenario}.json"
        result = RAW / f"bikeshare_{scenario}_result.json"
        if not (snap.exists() and result.exists()):
            snapshots_ok = False
            continue
        payload = json.loads(snap.read_text())
        snapshots_ok &= hashlib.sha256(payload["text"].encode()).hexdigest() == payload["sha256"]
        snapshots_ok &= json.loads(result.read_text())["csv"]["rows"] >= 500
    check("Part 4 scenarios: results + pricing snapshots with matching SHA-256, >= 500 rows", snapshots_ok)
    attacks = RAW / "prompt_injection_results.json"
    check("Part 5 before/after attack results saved", attacks.exists() and len(json.loads(attacks.read_text())) >= 3)
    check("Part 6 safety-gate results saved", (RAW / "safety_gate_results_final.json").exists())

    hw7_files = ["backend/jwt_auth.py", "backend/auth_api.py", "backend/security.py", "backend/report_api.py",
                 "backend/bikeshare_api.py", "src/agent_loop.py", "src/reflexion.py", "src/bikeshare_tools.py",
                 "src/bikeshare_agent.py", "src/file_tools.py", "scripts/verify_hw7.py", "tests"]
    lint = subprocess.run([str(ROOT / ".venv/bin/ruff"), "check", *hw7_files], cwd=ROOT, capture_output=True,
                          text=True)
    check("ruff passes on HW7 code", lint.returncode == 0, lint.stdout.strip().splitlines()[-1:])

    result = {
        "homework": 7,
        "SID4": SID4,
        "PORT_BASE": PORT_BASE,
        "SEED": SEED,
        "VERIFY_SEED": VERIFY_SEED,
        "commit": git("rev-parse", "HEAD") or "uncommitted",
        "tag_hw7_commit": git("rev-parse", "hw7^{commit}") or "missing",
        "working_tree_clean": git("status", "--porcelain", "--", "backend", "src", "scripts", "tests") == "",
        "model": "qwen3:4b via local Ollama (num_ctx 16384; agent loop temperature 0.2, seed 36)",
        "configuration": {"jwt_algorithm": "HS256", "access_token_minutes": 30, "database": "MySQL s0036_rel"},
        "checks": checks,
        "passed": all(item["passed"] for item in checks),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{sum(c['passed'] for c in checks)}/{len(checks)} checks passed -> {OUTPUT.relative_to(ROOT)}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
