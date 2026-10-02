from __future__ import annotations

import json
import tempfile
from pathlib import Path

from hw5_tools.agent import MockModel, run_agent
from hw5_tools.domain import DomainStore, execute_tool


def main() -> int:
    store = DomainStore.fixture()
    tests = {
        "search valid": lambda: json.loads(execute_tool("search", {"query": "open", "limit": 2}, store))["ok"],
        "search invalid query": lambda: not json.loads(execute_tool("search", {"query": ""}, store))["ok"],
        "detail valid": lambda: json.loads(execute_tool("detail", {"id": 1}, store))["data"]["package"] == "openssl",
        "detail invalid id": lambda: not json.loads(execute_tool("detail", {"id": "bad"}, store))["ok"],
        "aggregate valid": lambda: json.loads(execute_tool("aggregate", {}, store))["data"]["count"] == 2,
        "aggregate invalid severity": lambda: not json.loads(execute_tool("aggregate", {"severity": "urgent"}, store))["ok"],
        "safety rule blocked": lambda: not json.loads(execute_tool("aggregate", {"include_unavailable": True}, store))["ok"],
    }
    with tempfile.TemporaryDirectory() as directory:
        result = run_agent("keep going", MockModel([{"name": "search", "inputs": {"query": "open"}}] * 4),
                           max_steps=2, store=store, log_path=Path(directory) / "agent_runs.jsonl")
        tests["agent max_steps"] = lambda: result["stop_reason"] == "max_steps" and result["steps"] == 2
        passed = 0
        for name, test in tests.items():
            try:
                ok = bool(test())
            except Exception as exc:
                ok = False
                print(f"FAIL {name}: {exc}")
            print(f"{'PASS' if ok else 'FAIL'} {name}")
            passed += ok
    print(f"{passed}/{len(tests)} tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    raise SystemExit(main())
