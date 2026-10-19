"""File-based memory required by HW6 Part 4."""

from __future__ import annotations

import re
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.hw6_mongo_database import get_messages_collection
from src.model_client import ModelClient


ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = ROOT / "AGENT.md"
MEMORY_PATH = ROOT / "MEMORY.md"
CONSOLIDATED_RE = re.compile(r"<!--\s*consolidated_at:\s*([^>]+?)\s*-->")

DEFAULT_AGENT = """# Durable Agent Instructions

## Project description
- This project implements DATA-260 homework APIs for open-source package vulnerability analysis.

## Technology stack
- Use Python 3.12, FastAPI, Pydantic, PyMongo, MongoDB, and the local Ollama model.

## Coding conventions
- Keep route handlers thin and place business logic in separate service modules.
- Validate external input with Pydantic and return clear HTTP errors.

## Testing approach
- Test successful behavior, validation failures, persistence, and deterministic file operations before committing.

## Prohibited actions
- Do not expose secrets, delete unrelated user data, or modify unrelated homework evidence.
"""

DEFAULT_MEMORY = """# Durable Memory

<!-- consolidated_at: {timestamp} -->

- The project uses the `s0036_doc` MongoDB database for HW6 memory collections.
- The local model used for experiments is Ollama `qwen3:4b`.
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp() -> str:
    return _utc_now().isoformat()


def ensure_memory_files() -> None:
    """Create AGENT.md and MEMORY.md with defaults if they do not exist."""

    if not AGENT_PATH.exists():
        AGENT_PATH.write_text(DEFAULT_AGENT, encoding="utf-8")
    if not MEMORY_PATH.exists():
        MEMORY_PATH.write_text(DEFAULT_MEMORY.format(timestamp=_timestamp()), encoding="utf-8")


def load_memory_files() -> dict[str, str]:
    """Return the text of AGENT.md and MEMORY.md."""

    ensure_memory_files()
    return {
        "agent": AGENT_PATH.read_text(encoding="utf-8"),
        "memory": MEMORY_PATH.read_text(encoding="utf-8"),
    }


def _content_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and not line.lstrip().startswith("<!--")
    ]


def memory_line_count() -> int:
    """Return the number of non-empty, non-comment lines in MEMORY.md."""
    return len(_content_lines(load_memory_files()["memory"]))


def last_consolidated_at() -> datetime | None:
    """Return the consolidation timestamp recorded in MEMORY.md, or None."""

    match = CONSOLIDATED_RE.search(load_memory_files()["memory"])
    if not match:
        return None
    try:
        value = datetime.fromisoformat(match.group(1).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def consolidation_required() -> bool:
    """Return True if MEMORY.md has over 40 lines or was not consolidated in 24 hours."""

    timestamp = last_consolidated_at()
    return memory_line_count() > 40 or timestamp is None or _utc_now() - timestamp > timedelta(hours=24)


def file_memory_context() -> str:
    """Return AGENT.md and MEMORY.md formatted for the system prompt."""

    files = load_memory_files()
    return f"AGENT.md instructions:\n{files['agent']}\n\nMEMORY.md durable facts:\n{files['memory']}"


FACT_RE = re.compile(
    r"^-\s*(?:\[(?P<date>\d{4}-\d{2}-\d{2})\]\s*)?"
    r"(?:(?P<key>[a-z][a-z0-9_]*):\s+)?(?P<value>.+?)\s*(?:\(seen (?P<seen>\d+)x\))?$"
)
RESOLVED_HEADING = "## Resolved contradictions"
RESOLUTION_LINE_RE = re.compile(r'^-\s*[a-z][a-z0-9_]*: kept "')


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip().rstrip(".")


def parse_memory_facts(memory_text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Split MEMORY.md into fact records and previously recorded resolution lines."""

    facts: list[dict[str, Any]] = []
    resolved: list[str] = []
    in_resolved = False
    for order, raw in enumerate(memory_text.splitlines()):
        line = raw.strip()
        if line.startswith("#"):
            in_resolved = line == RESOLVED_HEADING
            continue
        if not line or line.startswith("<!--"):
            continue
        # Facts appended later (e.g. by /dream) land after this section, so only
        # lines in the resolution format belong to it.
        if in_resolved and RESOLUTION_LINE_RE.match(line):
            resolved.append(line)
            continue
        match = FACT_RE.match(line if line.startswith("-") else f"- {line}")
        if not match:
            continue
        facts.append({
            "date": match.group("date") or "",
            "key": match.group("key"),
            "value": match.group("value").strip(),
            "seen": int(match.group("seen") or 1),
            "order": order,
        })
    return facts, resolved


def _format_fact(fact: dict[str, Any]) -> str:
    date = f"[{fact['date']}] " if fact["date"] else ""
    key = f"{fact['key']}: " if fact["key"] else ""
    seen = f" (seen {fact['seen']}x)" if fact["seen"] > 1 else ""
    return f"- {date}{key}{fact['value']}{seen}"


def consolidate_memory_text(memory_text: str) -> tuple[str, dict[str, Any]]:
    """Merge duplicate facts and resolve contradictions without silent deletion.

    Duplicates (same key and value, ignoring case and spacing) are merged into
    one line with a "(seen Nx)" count. Facts that share a key but disagree are
    contradictions: the newest dated fact is kept and every superseded value is
    recorded under "## Resolved contradictions", so nothing disappears silently.
    """

    facts, previous_resolutions = parse_memory_facts(memory_text)
    before = len(_content_lines(memory_text))
    merged: dict[tuple[str | None, str], dict[str, Any]] = {}
    duplicates_merged = 0
    for fact in facts:
        identity = (fact["key"], _normalize(fact["value"]))
        if identity in merged:
            kept = merged[identity]
            kept["seen"] += fact["seen"]
            kept["date"] = max(kept["date"], fact["date"])
            duplicates_merged += 1
        else:
            merged[identity] = dict(fact)

    by_key: dict[str, list[dict[str, Any]]] = {}
    for fact in merged.values():
        if fact["key"]:
            by_key.setdefault(fact["key"], []).append(fact)

    resolutions: list[dict[str, Any]] = []
    superseded_ids: set[int] = set()
    for key, candidates in by_key.items():
        if len(candidates) < 2:
            continue
        ordered = sorted(candidates, key=lambda item: (item["date"], item["order"]))
        winner, losers = ordered[-1], ordered[:-1]
        superseded_ids.update(id(item) for item in losers)
        resolutions.append({
            "key": key,
            "kept": winner["value"],
            "kept_date": winner["date"],
            "superseded": [{"value": item["value"], "date": item["date"]} for item in losers],
            "rule": "newest dated fact wins",
        })

    kept_facts = sorted(
        (fact for fact in merged.values() if id(fact) not in superseded_ids),
        key=lambda item: item["order"],
    )
    resolution_lines = list(previous_resolutions)
    for item in resolutions:
        old = "; ".join(f'"{loser["value"]}" [{loser["date"] or "undated"}]' for loser in item["superseded"])
        resolution_lines.append(
            f'- {item["key"]}: kept "{item["kept"]}" [{item["kept_date"] or "undated"}]; superseded {old}'
        )

    lines = ["# Durable Memory", f"<!-- consolidated_at: {_timestamp()} -->", "## Facts"]
    lines += [_format_fact(fact) for fact in kept_facts]
    if resolution_lines:
        lines += ["", RESOLVED_HEADING] + resolution_lines
    text = "\n".join(lines) + "\n"
    return text, {
        "before": before,
        "after": len(_content_lines(text)),
        "file_lines_before": len(memory_text.splitlines()),
        "file_lines_after": len(text.splitlines()),
        "duplicates_merged": duplicates_merged,
        "contradictions_resolved": len(resolutions),
        "resolutions": resolutions,
    }


def audit_resolutions(
    resolutions: list[dict[str, Any]],
    ground_truth: dict[str, str],
) -> list[dict[str, str]]:
    """Return the contradiction resolutions whose kept value disagrees with ground truth.

    The newest-wins rule is only a heuristic, so each resolved key that has an
    authoritative value (for example from project configuration) is checked.
    """

    incorrect: list[dict[str, str]] = []
    for item in resolutions:
        expected = ground_truth.get(item["key"])
        if expected is not None and _normalize(item["kept"]) != _normalize(expected):
            incorrect.append({"key": item["key"], "kept": item["kept"], "expected": expected})
    return incorrect


def compact_memory() -> dict[str, Any]:
    """Consolidate MEMORY.md in place and report fact-line counts before and after."""

    files = load_memory_files()
    text, stats = consolidate_memory_text(files["memory"])
    MEMORY_PATH.write_text(text, encoding="utf-8")
    return {
        "message": (
            f"MEMORY.md consolidated: {stats['before']} -> {stats['after']} memory lines "
            f"({stats['file_lines_before']} -> {stats['file_lines_after']} file lines)"
        ),
        "message_count_before": stats["before"],
        "message_count_after": stats["after"],
        "file_lines_before": stats["file_lines_before"],
        "file_lines_after": stats["file_lines_after"],
        "duplicates_merged": stats["duplicates_merged"],
        "contradictions_resolved": stats["contradictions_resolved"],
        "resolutions": stats["resolutions"],
        "consolidation_required": consolidation_required(),
    }


def dream_memory(
    user_id: str,
    session_id: str | None,
    model_client: ModelClient,
) -> dict[str, Any]:
    """Ask the model for up to three new durable facts and append them to MEMORY.md."""

    files = load_memory_files()
    rows = list(
        get_messages_collection()
        .find({"user_id": user_id, "session_id": session_id, "role": "user"})
        .sort("created_at", -1)
        .limit(10)
    )
    rows.reverse()
    transcript = "\n".join(item["content"] for item in rows if not item["content"].startswith("/"))
    if not transcript:
        return {"message": "No recent user conversation is available for /dream.", "facts_added": []}
    result = model_client.complete([
        {
            "role": "system",
            "content": (
                "Identify up to three durable, useful facts from the conversation. "
                "Return only short markdown bullet lines. Do not invent facts."
            ),
        },
        {"role": "user", "content": f"Conversation:\n{transcript}\n\nExisting memory:\n{files['memory']}"},
    ])
    existing = {_normalize(fact["value"]) for fact in parse_memory_facts(files["memory"])[0]}
    today = _utc_now().date().isoformat()
    facts = []
    for line in result.text.splitlines():
        value = line.strip().lstrip("-*").strip()
        if line.strip().startswith(("-", "*")) and value and _normalize(value) not in existing:
            facts.append(f"- [{today}] {value}")
    facts = facts[:3]
    if not facts:
        return {"message": "No new durable facts were identified.", "facts_added": []}
    with MEMORY_PATH.open("a", encoding="utf-8") as stream:
        stream.write("\n" + "\n".join(facts) + "\n")
    return {"message": "Durable facts added to MEMORY.md", "facts_added": facts}


def help_text() -> str:
    """Return the help text listing the file-memory commands."""
    return (
        "/memory — display AGENT.md and MEMORY.md\n"
        "/compact — merge duplicates, resolve contradictions, report memory-line counts before and after\n"
        "/dream — identify durable facts from recent conversation and add them to MEMORY.md\n"
        "/help — display these commands"
    )


def verify_agent_instructions() -> dict[str, Any]:
    """Verify that AGENT.md covers the required instruction categories."""

    text = load_memory_files()["agent"]
    required_sections = {
        "project_description": "## Project description",
        "technology_stack": "## Technology stack",
        "coding_conventions": "## Coding conventions",
        "testing_approach": "## Testing approach",
        "prohibited_actions": "## Prohibited actions",
    }
    checks = {name: marker in text for name, marker in required_sections.items()}
    try:
        route_source = (ROOT / "backend" / "hw6_memory_api.py").read_text(encoding="utf-8")
        tree = ast.parse(route_source)
        route_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        checks["route_handlers_exist"] = route_names >= {"chat", "memory", "aggregate"}
        checks["chat_delegates_to_service"] = "make_chat_turn" in route_source
        checks["request_validation_is_declared"] = "Field(min_length=1)" in route_source
    except Exception:
        checks["route_handlers_exist"] = False
        checks["chat_delegates_to_service"] = False
        checks["request_validation_is_declared"] = False
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "instruction_count": len(_content_lines(text)),
    }


def handle_file_memory_command(
    command: str,
    user_id: str,
    session_id: str | None,
    model_client: ModelClient,
) -> dict[str, Any] | None:
    """Run /memory, /compact, /dream or /help; return None for other messages."""

    normalized = command.strip().casefold()
    if normalized == "/memory":
        files = load_memory_files()
        return {
            "message": "Current file-based memory",
            "agent": files["agent"],
            "memory": files["memory"],
            "memory_line_count": memory_line_count(),
            "last_consolidated_at": str(last_consolidated_at()),
            "consolidation_required": consolidation_required(),
        }
    if normalized == "/compact":
        return compact_memory()
    if normalized == "/dream":
        return dream_memory(user_id, session_id, model_client)
    if normalized == "/help":
        return {"message": help_text()}
    return None
