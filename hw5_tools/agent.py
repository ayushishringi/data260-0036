from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .domain import DomainStore, execute_tool

LOGGER = logging.getLogger("s0036_agent")


class MockModel:
    def __init__(self, calls: list[dict[str, Any]] | None = None):
        self.calls = calls or [{"name": "search", "inputs": {"query": "openssl", "limit": 1}}]
        self.index = 0

    def next_call(self, _user_input: str, _history: list[dict[str, Any]]) -> dict[str, Any] | None:
        if self.index >= len(self.calls):
            return None
        call = self.calls[self.index]
        self.index += 1
        return call


def run_agent(user_input: str, model: Any | None = None, *, max_steps: int = 5,
              store: DomainStore | None = None, log_path: str | Path = "agent_runs.jsonl") -> dict[str, Any]:
    model = model or MockModel()
    store = store or DomainStore.fixture()
    history: list[dict[str, Any]] = []
    stop_reason = "max_steps"
    for step in range(1, max_steps + 1):
        call = model.next_call(user_input, history)
        if call is None:
            stop_reason = "normal_completion"
            break
        result = json.loads(execute_tool(call.get("name", ""), call.get("inputs", {}), store))
        event = {"step": step, "user_input": user_input, "tool": call.get("name"),
                 "inputs": call.get("inputs", {}), "result": result}
        history.append(event)
        with Path(log_path).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
        if not result["ok"] and result["error"].startswith("safety rule"):
            stop_reason = "safety_rule_block"
            break
    summary = {"steps": len(history), "tool_call_count": len(history), "stop_reason": stop_reason}
    with Path(log_path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"final": summary}, sort_keys=True) + "\n")
    return {**summary, "events": history}
