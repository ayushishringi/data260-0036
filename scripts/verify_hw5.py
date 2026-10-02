from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def commit_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "refs/tags/hw5^{}"], cwd=ROOT, text=True).strip()
    except Exception:
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        except Exception:
            return "uncommitted"


def main() -> int:
    test = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_hw5_tests.py")], cwd=ROOT, capture_output=True, text=True)
    files = ["backend/models.py", "backend/report_api.py", "frontend/src/store.js", "domain_mcp_server.py",
             "meals_server.py", "scripts/run_hw5_tests.py", "scripts/run_hw5_faults.py", "reports/hw05/METRICS.md"]
    checks = {"offline_tool_tests": {"passed": test.returncode == 0, "output": test.stdout},
              "required_files": {name: (ROOT / name).exists() for name in files}}
    checks["all_required_files_present"] = all(checks["required_files"].values())
    result = {"passed": checks["offline_tool_tests"]["passed"] and checks["all_required_files_present"],
              "homework": "DATA-260 HW5", "SID4": "0036", "PORT_BASE": 8036, "PREFIX": "s0036",
              "SEED": 36, "VERIFY_SEED": 260036, "DOMAIN_ID": 4, "commit_hash": commit_hash(),
              "model": "qwen3:4b (Ollama; offline tests use MockModel)", "checks": checks}
    path = ROOT / "reports" / "hw05" / "verification.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
