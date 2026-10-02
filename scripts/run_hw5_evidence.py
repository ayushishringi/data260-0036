from __future__ import annotations

import json
from pathlib import Path

from hw5_tools.agent import MockModel, run_agent
from hw5_tools.domain import DomainStore, execute_tool

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "reports" / "hw05" / "raw"


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    store = DomainStore.fixture()
    scenarios = [
        ("normal_completion", MockModel([]), 3),
        ("max_steps", MockModel([{"name": "search", "inputs": {"query": "open"}}] * 5), 2),
        ("safety_rule_block", MockModel([{"name": "aggregate", "inputs": {"include_unavailable": True}}]), 3),
        ("invalid_tool_input", MockModel([{"name": "detail", "inputs": {"id": "bad"}}]), 3),
    ]
    lines = []
    for label, model, limit in scenarios:
        result = run_agent(label, model, max_steps=limit, store=store, log_path=RAW / "agent_runs.jsonl")
        lines.append({"scenario": label, **{key: result[key] for key in ("steps", "stop_reason", "tool_call_count")}})
    (RAW / "agent_scenarios.json").write_text(json.dumps(lines, indent=2) + "\n", encoding="utf-8")
    inspector = {
        "domain": {"search_valid": json.loads(execute_tool("search", {"query": "open"}, store)),
                   "search_invalid": json.loads(execute_tool("search", {"query": ""}, store)),
                   "detail_valid": json.loads(execute_tool("detail", {"id": 1}, store)),
                   "detail_invalid": json.loads(execute_tool("detail", {"id": "bad"}, store)),
                   "aggregate_valid": json.loads(execute_tool("aggregate", {}, store)),
                   "aggregate_invalid": json.loads(execute_tool("aggregate", {"severity": "urgent"}, store))},
        "meals": "Run mcp dev meals_server.py and capture four Inspector calls when network is available.",
    }
    (RAW / "mcp_inspector_outputs.json").write_text(json.dumps(inspector, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
