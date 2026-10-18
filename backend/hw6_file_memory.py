"""File-based memory required by HW6 Part 4."""

from __future__ import annotations

import re
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
    if not AGENT_PATH.exists():
        AGENT_PATH.write_text(DEFAULT_AGENT, encoding="utf-8")
    if not MEMORY_PATH.exists():
        MEMORY_PATH.write_text(DEFAULT_MEMORY.format(timestamp=_timestamp()), encoding="utf-8")


def load_memory_files() -> dict[str, str]:
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
    return len(_content_lines(load_memory_files()["memory"]))


def last_consolidated_at() -> datetime | None:
    match = CONSOLIDATED_RE.search(load_memory_files()["memory"])
    if not match:
        return None
    try:
        value = datetime.fromisoformat(match.group(1).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def consolidation_required() -> bool:
    timestamp = last_consolidated_at()
    return memory_line_count() > 40 or timestamp is None or _utc_now() - timestamp > timedelta(hours=24)


def file_memory_context() -> str:
    files = load_memory_files()
    return f"AGENT.md instructions:\n{files['agent']}\n\nMEMORY.md durable facts:\n{files['memory']}"


def compact_memory() -> dict[str, Any]:
    files = load_memory_files()
    before = len(_content_lines(files["memory"]))
    unique_lines: list[str] = []
    seen: set[str] = set()
    for line in _content_lines(files["memory"]):
        key = line.casefold()
        if key not in seen:
            unique_lines.append(line)
            seen.add(key)
    unique_lines = unique_lines[:40]
    text = "# Durable Memory\n\n<!-- consolidated_at: " + _timestamp() + " -->\n\n"
    text += "\n".join(f"- {line.lstrip('- ').strip()}" for line in unique_lines)
    text += "\n"
    MEMORY_PATH.write_text(text, encoding="utf-8")
    return {
        "message": "MEMORY.md consolidated",
        "message_count_before": before,
        "message_count_after": len(unique_lines),
        "consolidation_required": False,
    }


def dream_memory(
    user_id: str,
    session_id: str | None,
    model_client: ModelClient,
) -> dict[str, Any]:
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
    facts = [line.strip() for line in result.text.splitlines() if line.strip().startswith("-")]
    facts = facts[:3]
    if not facts:
        return {"message": "No durable facts were identified.", "facts_added": []}
    with MEMORY_PATH.open("a", encoding="utf-8") as stream:
        stream.write("\n" + "\n".join(facts) + "\n")
    return {"message": "Durable facts added to MEMORY.md", "facts_added": facts}


def help_text() -> str:
    return (
        "/memory — display AGENT.md and MEMORY.md\n"
        "/compact — consolidate MEMORY.md and report the line count before and after\n"
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
    normalized = command.strip().casefold()
    if normalized == "/memory":
        files = load_memory_files()
        return {"message": "Current file-based memory", "agent": files["agent"], "memory": files["memory"]}
    if normalized == "/compact":
        return compact_memory()
    if normalized == "/dream":
        return dream_memory(user_id, session_id, model_client)
    if normalized == "/help":
        return {"message": help_text()}
    return None
