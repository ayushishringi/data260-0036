"""Hand-written tool-calling agent loop (HW7 Part 2).

run_agent() sends the conversation plus JSON-schema tool definitions to the HW1
model adapter, executes every tool call the model makes, appends each result as
a tool-role message, and repeats until the model answers in text or a hard
iteration ceiling is reached.

Repair path: an unknown tool name, malformed arguments, a schema violation, or a
text reply before any tool was used is reported back to the model once with the
specific problem; after `max_repairs` failed repairs the run stops cleanly with
stop_reason "repair_limit".
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hw5_tools.domain import DomainStore, execute_tool
from src.model_client import ModelClient

LOGGER = logging.getLogger("s0036.agent_loop")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATH = ROOT / "reports" / "hw07" / "raw" / "agent_tool_log.jsonl"

MALFORMED = "malformed_arguments"
UNKNOWN_TOOL = "unknown_tool"
TEXT_INSTEAD_OF_TOOL = "text_when_tool_required"
LOST_CHAIN = "lost_multi_step_chain"


@dataclass(frozen=True)
class ToolSpec:
    """One tool: name, description, JSON schema for its arguments, and a handler returning a dict."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


# ----------------------------------------------------------------------------- domain tools (HW5)

SEVERITIES = ["critical", "high", "medium", "low"]


def domain_tools(store: DomainStore | None = None) -> list[ToolSpec]:
    """The three HW5 domain tools, executed through hw5_tools.domain.execute_tool."""

    store = store or DomainStore.hw7_fixture()

    def run(name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        return lambda args: json.loads(execute_tool(name, args, store))

    return [
        ToolSpec(
            "search",
            "Search the vulnerability inventory by package-name substring. Returns only the id and package "
            "name of each match; use detail(id) for severity, available_count and advisory_code. Pass "
            "severity to filter by severity.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Package name or part of it, e.g. 'openssl'"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                    "severity": {"type": "string", "enum": SEVERITIES},
                },
                "additionalProperties": False,
            },
            run("search"),
        ),
        ToolSpec(
            "detail",
            "Get the full vulnerability record for one integer record id (from a search result).",
            {
                "type": "object",
                "properties": {"id": {"type": "integer", "minimum": 1}},
                "required": ["id"],
                "additionalProperties": False,
            },
            run("detail"),
        ),
        ToolSpec(
            "aggregate",
            "Count records in the inventory, optionally for one severity. Returns count, "
            "available_count_total and a by_severity breakdown.",
            {
                "type": "object",
                "properties": {"severity": {"type": "string", "enum": SEVERITIES}},
                "additionalProperties": False,
            },
            run("aggregate"),
        ),
    ]


DOMAIN_SYSTEM_PROMPT = (
    "You are an agent for a vulnerability inventory (DATA-260, s0036). You can only learn facts by "
    "calling the tools; never invent records, ids, counts or advisory codes. Complete every step the "
    "user asks for by calling tools one after another, exactly one tool call per message, without asking "
    "follow-up questions. Never repeat "
    "a tool call you already made with the same arguments. When you have all the facts, answer in at "
    "most 4 sentences and cite the record ids you used. /no_think"
)


# ----------------------------------------------------------------------------- validation

JSON_TYPES: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
}


def validate_arguments(arguments: Any, schema: dict[str, Any]) -> str | None:
    """Return a specific problem description, or None if the arguments satisfy the schema."""

    if not isinstance(arguments, dict):
        return f"arguments must be a JSON object, got {type(arguments).__name__}"
    properties = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in arguments:
            return f"missing required argument '{key}'"
    if schema.get("additionalProperties") is False:
        extra = sorted(set(arguments) - set(properties))
        if extra:
            return f"unknown argument(s) {extra}; allowed: {sorted(properties)}"
    for key, value in arguments.items():
        rules = properties.get(key, {})
        expected = rules.get("type")
        if expected and not JSON_TYPES[expected](value):
            return f"argument '{key}' must be {expected}, got {type(value).__name__} {value!r}"
        if "enum" in rules and value not in rules["enum"]:
            return f"argument '{key}' must be one of {rules['enum']}, got {value!r}"
        if "minimum" in rules and value < rules["minimum"]:
            return f"argument '{key}' must be >= {rules['minimum']}, got {value!r}"
        if "maximum" in rules and value > rules["maximum"]:
            return f"argument '{key}' must be <= {rules['maximum']}, got {value!r}"
    return None


TEXT_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", re.DOTALL)


def parse_tool_calls(message: dict[str, Any], tool_names: set[str] | None = None) -> list[dict[str, Any]]:
    """Normalize the model's tool calls to {"name", "arguments", "parse_error"}.

    Native calls arrive in message["tool_calls"]. A call written as text inside
    <tool_call> tags (the model's fallback format) is parsed too, so a broken
    JSON body is caught as malformed arguments instead of being lost.
    """

    calls = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function", {})
        arguments = function.get("arguments", {})
        parse_error = None
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError as exc:
                parse_error = f"arguments are not valid JSON ({exc.msg})"
        calls.append({"name": function.get("name", ""), "arguments": arguments, "parse_error": parse_error})
    if calls:
        return calls
    content = message.get("content") or ""
    for body in TEXT_TOOL_CALL_RE.findall(content):
        try:
            parsed = json.loads(body)
            calls.append({"name": parsed.get("name", ""), "arguments": parsed.get("arguments", {}),
                          "parse_error": None})
        except (json.JSONDecodeError, AttributeError) as exc:
            calls.append({"name": "", "arguments": body, "parse_error": f"tool call is not valid JSON ({exc})"})
    if calls or tool_names is None:
        return calls
    # Last resort: a bare {"name": <registered tool>, "arguments": {...}} written as plain text
    # (seen with Ollama 0.40 when the model narrates its plan instead of emitting a native call).
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{\s*"name"\s*:', content):
        try:
            parsed, _ = decoder.raw_decode(content[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("name") in tool_names and "arguments" in parsed:
            calls.append({"name": parsed["name"], "arguments": parsed["arguments"], "parse_error": None,
                          "from_text": True})
    return calls[-1:]  # the model's latest stated call


# ----------------------------------------------------------------------------- the loop


def _log(event: dict[str, Any], log_path: Path | None) -> None:
    if log_path is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, default=str) + "\n")


def run_agent(
    user_input: str,
    *,
    tools: list[ToolSpec] | None = None,
    client: ModelClient | None = None,
    system_prompt: str = DOMAIN_SYSTEM_PROMPT,
    context_messages: list[dict[str, str]] | None = None,
    max_iterations: int = 8,
    max_repairs: int = 2,
    require_tool: bool = True,
    temperature: float = 0.2,
    seed: int | None = None,
    think: bool = False,
    tool_call_budget: int | None = None,
    token_budget: int | None = None,
    run_id: str | None = None,
    log_path: Path | None = DEFAULT_LOG_PATH,
    echo: bool = True,
) -> dict[str, Any]:
    """Run the tool loop for one user request and return the answer, stop reason and full trace."""

    tools = tools if tools is not None else domain_tools()
    registry = {tool.name: tool for tool in tools}
    client = client or ModelClient()
    run_id = run_id or uuid.uuid4().hex[:10]
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages += context_messages or []
    messages.append({"role": "user", "content": user_input})

    started = time.perf_counter()
    trace: list[dict[str, Any]] = []        # every executed tool call with its observation
    attempts: list[dict[str, Any]] = []     # every call the model emitted, valid or not
    repairs: list[dict[str, Any]] = []
    tokens = {"input": 0, "output": 0}
    skipped_calls = 0
    final_answer, stop_reason = "", "max_iterations"

    def say(line: str) -> None:
        LOGGER.info(line)
        if echo:
            print(line, flush=True)

    for iteration in range(1, max_iterations + 1):
        if tool_call_budget is not None and len(trace) >= tool_call_budget:
            stop_reason = "budget_exhausted"
            break
        if token_budget is not None and tokens["input"] + tokens["output"] >= token_budget:
            stop_reason = "budget_exhausted"
            break
        result = client.complete(messages, tools=[tool.schema() for tool in tools],
                                 temperature=temperature, seed=seed, think=think)
        tokens["input"] += result.input_tokens
        tokens["output"] += result.output_tokens
        message = result.raw.get("message", {})
        calls = parse_tool_calls(message, set(registry))

        if not calls:
            if require_tool and not trace:
                problem = "you replied with text, but this request requires tool calls; call a tool now"
                attempts.append({"iteration": iteration, "name": None, "arguments": None,
                                 "ok": False, "category": TEXT_INSTEAD_OF_TOOL, "problem": problem})
                repairs.append({"iteration": iteration, "category": TEXT_INSTEAD_OF_TOOL, "problem": problem})
                say(f"[{run_id}] repair #{len(repairs)} ({TEXT_INSTEAD_OF_TOOL}): {problem}")
                if len(repairs) > max_repairs:
                    stop_reason = "repair_limit"
                    break
                messages.append({"role": "assistant", "content": result.text})
                messages.append({"role": "user", "content": f"Problem: {problem}. Available tools: "
                                 f"{', '.join(registry)}."})
                continue
            final_answer, stop_reason = result.text, "final_answer"
            break

        # One tool call per turn: these tasks are sequential (a detail lookup needs the search
        # result first), and parallel batches from the model contained guessed ids. Extra calls
        # are not executed; the model is told so and can issue them on the next turn.
        skipped = calls[1:]
        calls = calls[:1]
        raw_calls = message.get("tool_calls") or [{"function": {"name": c["name"], "arguments": c["arguments"]}}
                                                  for c in calls]
        messages.append({"role": "assistant", "content": result.text, "tool_calls": raw_calls[:1]})
        if skipped:
            skipped_calls += len(skipped)
            say(f"[{run_id}] note: model sent {len(skipped) + 1} calls in one turn; executing only the first")
        repair_needed = False
        for call in calls:
            name, arguments = call["name"], call["arguments"]
            category, problem = None, None
            if call["parse_error"]:
                category, problem = MALFORMED, call["parse_error"]
            elif name not in registry:
                category, problem = UNKNOWN_TOOL, f"unknown tool '{name}'; available tools: {sorted(registry)}"
            else:
                schema_problem = validate_arguments(arguments, registry[name].parameters)
                if schema_problem:
                    category, problem = MALFORMED, schema_problem
            attempt = {"iteration": iteration, "name": name, "arguments": arguments,
                       "ok": category is None, "category": category, "problem": problem}
            attempts.append(attempt)
            if category:
                repair_needed = True
                repairs.append({"iteration": iteration, "category": category, "problem": problem, "name": name})
                say(f"[{run_id}] repair #{len(repairs)} ({category}): {name} {json.dumps(arguments, default=str)}"
                    f" -> {problem}")
                content = json.dumps({"ok": False, "error": f"REPAIR NEEDED: {problem}. Correct the call."})
            else:
                tool_started = time.perf_counter()
                try:
                    observation = registry[name].handler(arguments)
                except Exception as exc:  # the tool boundary never crashes the loop
                    observation = {"ok": False, "error": f"tool failure: {exc}"}
                latency = round((time.perf_counter() - tool_started) * 1000, 2)
                trace.append({"step": len(trace) + 1, "iteration": iteration, "tool": name,
                              "inputs": arguments, "observation": observation, "latency_ms": latency})
                ok = observation.get("ok", observation.get("success"))
                say(f"[{run_id}] tool #{len(trace)} {name} {json.dumps(arguments, sort_keys=True)} -> "
                    f"{'ok' if ok else 'error: ' + str(observation.get('error'))}")
                _log({"run_id": run_id, "step": len(trace), "tool": name, "inputs": arguments,
                      "ok": ok, "latency_ms": latency}, log_path)
                content = json.dumps(observation, sort_keys=True, default=str)
            if skipped and not category:
                observation_note = json.loads(content)
                observation_note["note"] = (f"{len(skipped)} other tool call(s) in your message were not executed; "
                                            "make one tool call per message, using results you have seen.")
                content = json.dumps(observation_note, sort_keys=True, default=str)
            messages.append({"role": "tool", "tool_name": name or "invalid", "content": content})
        if repair_needed and len(repairs) > max_repairs:
            stop_reason = "repair_limit"
            break

    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    summary = {
        "run_id": run_id,
        "final_answer": final_answer,
        "stop_reason": stop_reason,
        "total_tool_calls": len(trace),
        "iterations": iteration,
        "trace": trace,
        "emitted_calls": attempts,
        "repairs": repairs,
        "skipped_parallel_calls": skipped_calls,
        "tokens": tokens,
        "latency_ms": latency_ms,
    }
    say(f"[{run_id}] done: stop_reason={stop_reason} total_tool_calls={len(trace)} repairs={len(repairs)} "
        f"tokens={tokens['input'] + tokens['output']} latency_ms={latency_ms}")
    _log({"run_id": run_id, "final": {k: summary[k] for k in ("stop_reason", "total_tool_calls", "latency_ms")}},
         log_path)
    return summary
