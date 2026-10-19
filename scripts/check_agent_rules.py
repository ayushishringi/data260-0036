"""HW6 Part 4.4: verify that one generated function follows the rules in AGENT.md.

Target: backend.hw6_file_memory.audit_resolutions (generated with an AI assistant
while AGENT.md was in the prompt). Each check maps to one AGENT.md instruction.
Writes reports/hw06/raw/agent_rule_check.json.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "backend" / "hw6_file_memory.py"
TARGET = "audit_resolutions"
TEST_FILE = ROOT / "tests" / "test_hw6_file_memory.py"
OUTPUT = ROOT / "reports" / "hw06" / "raw" / "agent_rule_check.json"


def find_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise SystemExit(f"{name} not found in {MODULE}")


def called_names(node: ast.AST) -> set[str]:
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            names.add(func.id if isinstance(func, ast.Name) else getattr(func, "attr", ""))
    return names


def main() -> int:
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = find_function(tree, TARGET)
    arguments = function.args.args + function.args.kwonlyargs
    calls = called_names(function)
    int_literals = [
        node.value for node in ast.walk(function)
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool)
    ]
    agent_text = (ROOT / "AGENT.md").read_text(encoding="utf-8")

    test_run = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", "tests.test_hw6_file_memory"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    checks = {
        "full_type_hints": {
            "rule": "Every public function has full type hints",
            "passed": all(arg.annotation is not None for arg in arguments) and function.returns is not None,
        },
        "has_docstring": {
            "rule": "and a docstring",
            "passed": ast.get_docstring(function) is not None,
        },
        "no_print_in_backend_module": {
            "rule": "Do not use `print()` in `backend/` modules",
            "passed": "print" not in called_names(tree),
        },
        "pure_function_no_file_writes": {
            "rule": "Do not silently delete facts from MEMORY.md",
            "passed": not ({"write_text", "open", "unlink", "remove"} & calls),
        },
        "no_hosted_model_api": {
            "rule": "Do not call paid hosted model APIs",
            "passed": not any(host in source for host in ("api.openai.com", "api.anthropic.com", "openai", "anthropic")),
        },
        "no_hard_coded_port": {
            "rule": "the API runs on PORT_BASE 8036",
            "passed": not any(value >= 1024 and value != 8036 for value in int_literals),
        },
        "unittest_exists": {
            "rule": "Every new pure function gets a `unittest` test in `tests/`",
            "passed": TEST_FILE.exists() and TARGET in TEST_FILE.read_text(encoding="utf-8"),
        },
        "unittests_pass": {
            "rule": "before committing",
            "passed": test_run.returncode == 0,
        },
    }
    for check in checks.values():
        check["rule_in_agent_md"] = check["rule"] in agent_text
    result = {
        "target": f"backend/hw6_file_memory.py::{TARGET}",
        "passed": all(check["passed"] and check["rule_in_agent_md"] for check in checks.values()),
        "checks": checks,
        "unittest_output": test_run.stderr.strip().splitlines()[-12:],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
