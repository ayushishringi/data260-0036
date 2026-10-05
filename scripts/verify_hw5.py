from __future__ import annotations

import json
import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def runtime_entrypoint_checks() -> dict[str, object]:
    """Verify that the API and both MCP server entry points are loadable."""
    checks: dict[str, object] = {}
    try:
        api = importlib.import_module("backend.main")
        paths = {getattr(route, "path", "") for route in api.app.routes}
        checks["fastapi_app_import"] = True
        checks["fastapi_health_route"] = "/api/health" in paths
        checks["fastapi_reports_route"] = "/api/reports" in paths
    except Exception as exc:
        checks["fastapi_app_import"] = False
        checks["fastapi_error"] = str(exc)

    for module_name, label, expected_tools in (
        ("domain_mcp_server", "domain_mcp", {"search", "detail", "aggregate"}),
        ("meals_server", "meals_mcp", {
            "search_meals_by_name", "meals_by_ingredient", "random_meal", "meal_details"
        }),
    ):
        try:
            module = importlib.import_module(module_name)
            server = getattr(module, "mcp", None)
            tool_manager = getattr(server, "_tool_manager", None)
            registered = set(getattr(tool_manager, "_tools", {}).keys())
            checks[f"{label}_import"] = server is not None
            checks[f"{label}_tools"] = sorted(expected_tools & registered)
            checks[f"{label}_tools_complete"] = expected_tools <= registered
        except Exception as exc:
            checks[f"{label}_import"] = False
            checks[f"{label}_error"] = str(exc)

    checks["runtime_entrypoints_ready"] = all(
        value is True
        for key, value in checks.items()
        if key.endswith("_import") or key.endswith("_route") or key.endswith("_complete")
    )
    return checks


def main() -> int:
    test = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_hw5_tests.py")], cwd=ROOT, capture_output=True, text=True)
    files = ["backend/models.py", "backend/report_api.py", "frontend/src/store.js", "domain_mcp_server.py",
             "meals_server.py", "scripts/run_hw5_tests.py", "scripts/run_hw5_faults.py",
             "scripts/run_retry_cases.py", "reports/hw05/METRICS.md"]
    checks = {"offline_tool_tests": {"passed": test.returncode == 0, "output": test.stdout},
              "required_files": {name: (ROOT / name).exists() for name in files}}
    checks["all_required_files_present"] = all(checks["required_files"].values())
    checks["runtime_entrypoints"] = runtime_entrypoint_checks()
    result = {"passed": checks["offline_tool_tests"]["passed"] and checks["all_required_files_present"]
              and checks["runtime_entrypoints"]["runtime_entrypoints_ready"],
              "homework": "DATA-260 HW5", "SID4": "0036", "PORT_BASE": 8036, "PREFIX": "s0036",
              "SEED": 36, "VERIFY_SEED": 260036, "DOMAIN_ID": 4,
              "model": "qwen3:4b (Ollama; offline tests use MockModel)", "checks": checks}
    path = ROOT / "reports" / "hw05" / "verification.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
