"""Objective repository smoke checks for DATA-260 HW6."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "reports" / "hw06" / "verification.json"


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or "uncommitted"


def main() -> int:
    checks: dict[str, object] = {}
    required_files = [
        "AGENT.md",
        "MEMORY.md",
        "backend/hw6_file_memory.py",
        "backend/hw6_memory_service.py",
        "backend/hw6_memory_api.py",
        "memory_probes.yaml",
        "reports/hw06/METRICS.md",
        "reports/hw06/raw/chat_costs.jsonl",
        "reports/hw06/raw/memory_cost_comparison.json",
    ]
    checks["required_files"] = {name: (ROOT / name).exists() for name in required_files}
    checks["required_files_present"] = all(checks["required_files"].values())

    try:
        from backend.main import app
        paths = set(app.openapi().get("paths", {}))
        checks["fastapi_app_import"] = True
        checks["chat_route"] = "/api/chat" in paths
        checks["memory_route"] = "/api/memory/{user_id}" in paths
        checks["aggregate_route"] = "/api/aggregate/{user_id}" in paths
    except Exception as exc:
        checks["fastapi_app_import"] = False
        checks["fastapi_error"] = str(exc)

    try:
        from backend.hw6_file_memory import verify_agent_instructions
        checks["agent_instructions"] = verify_agent_instructions()
    except Exception as exc:
        checks["agent_instructions"] = {"passed": False, "error": str(exc)}

    probes = yaml.safe_load((ROOT / "memory_probes.yaml").read_text(encoding="utf-8"))
    checks["memory_probe_count"] = len(probes.get("probes", []))
    checks["five_memory_probes"] = checks["memory_probe_count"] == 5

    comparison = json.loads(
        (ROOT / "reports/hw06/raw/memory_cost_comparison.json").read_text(encoding="utf-8")
    )
    settings = {(item["short_term_n"], item["policy"]) for item in comparison["settings"]}
    expected_settings = {(4, "window"), (12, "window"), (30, "window"), (4, "summary_compression")}
    checks["comparison_settings"] = sorted([list(item) for item in settings])
    checks["four_comparison_settings"] = settings == expected_settings

    compile_result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "backend", "scripts/run_hw6_memory_cost.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks["python_compile"] = compile_result.returncode == 0

    checks["passed"] = all([
        checks["required_files_present"],
        checks.get("fastapi_app_import", False),
        checks.get("chat_route", False),
        checks.get("memory_route", False),
        checks.get("aggregate_route", False),
        checks.get("agent_instructions", {}).get("passed", False),
        checks["five_memory_probes"],
        checks["four_comparison_settings"],
        checks["python_compile"],
    ])
    result = {
        "passed": checks["passed"],
        "homework": "DATA-260 HW6",
        "SID4": "0036",
        "PORT_BASE": 8036,
        "PREFIX": "s0036",
        "SEED": 36,
        "VERIFY_SEED": 260036,
        "DOMAIN_ID": 4,
        "commit": git_commit(),
        "model": "qwen3:4b (Ollama)",
        "checks": checks,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
