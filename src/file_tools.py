"""File tools and a bash safety gate (HW7 Part 6).

All file tools operate inside one sandbox root (set_sandbox); paths that resolve
outside it are rejected. bash() runs only after confirm_bash() allows the
command. The gate is pure Python and needs no model:

* SAFE_PREFIXES - read-only commands that may run without confirmation.
* is_destructive(command) - an independent deny-list check. A destructive
  command is blocked unless auto_approve=True, even if it starts with a safe
  prefix (e.g. "ls; rm -rf /").
"""

from __future__ import annotations

import difflib
import fnmatch
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

_SANDBOX: Path | None = None


def set_sandbox(root: str | Path) -> Path:
    """Restrict every file tool to this directory."""

    global _SANDBOX
    _SANDBOX = Path(root).resolve()
    _SANDBOX.mkdir(parents=True, exist_ok=True)
    return _SANDBOX


def _resolve(path: str) -> Path:
    if _SANDBOX is None:
        raise PermissionError("no sandbox set; call set_sandbox() first")
    candidate = (_SANDBOX / path).resolve()
    if candidate != _SANDBOX and _SANDBOX not in candidate.parents:
        raise PermissionError(f"path escapes the sandbox: {path}")
    return candidate


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _err(message: str) -> dict[str, Any]:
    return {"ok": False, "data": None, "error": message}


def _rel(path: Path) -> str:
    return str(path.relative_to(_SANDBOX)) if _SANDBOX else str(path)


# ----------------------------------------------------------------------------- file tools


def read_file(path: str, max_lines: int | None = None) -> dict[str, Any]:
    """Return the file text, truncated to the first max_lines lines when given."""

    try:
        target = _resolve(path)
        lines = target.read_text(encoding="utf-8").splitlines()
    except (OSError, PermissionError, UnicodeDecodeError) as exc:
        return _err(str(exc))
    shown = lines if max_lines is None else lines[: max(0, int(max_lines))]
    return _ok({"path": _rel(target), "content": "\n".join(shown), "total_lines": len(lines),
                "truncated": len(shown) < len(lines)})


def write_file(path: str, content: str) -> dict[str, Any]:
    """Create or overwrite a file inside the sandbox."""

    try:
        target = _resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except (OSError, PermissionError) as exc:
        return _err(str(exc))
    return _ok({"path": _rel(target), "bytes": len(content.encode("utf-8"))})


def edit_file(path: str, old: str, new: str) -> dict[str, Any]:
    """Replace exactly one occurrence of `old` with `new` and return a short unified diff."""

    try:
        target = _resolve(path)
        before = target.read_text(encoding="utf-8")
    except (OSError, PermissionError, UnicodeDecodeError) as exc:
        return _err(str(exc))
    count = before.count(old)
    if count != 1:
        return _err(f"'old' must occur exactly once, found {count} occurrences")
    after = before.replace(old, new, 1)
    target.write_text(after, encoding="utf-8")
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), f"a/{_rel(target)}",
                                f"b/{_rel(target)}", n=1, lineterm="")
    return _ok({"path": _rel(target), "diff": "\n".join(list(diff)[:20])})


def glob_files(pattern: str, path: str = ".") -> dict[str, Any]:
    """List sandbox files matching a glob pattern such as '**/*.py'."""

    try:
        base = _resolve(path)
    except PermissionError as exc:
        return _err(str(exc))
    matches = sorted(_rel(p) for p in base.glob(pattern) if p.is_file())
    return _ok({"pattern": pattern, "matches": matches, "count": len(matches)})


def search_in_files(pattern: str, path: str = ".", file_pattern: str = "*") -> dict[str, Any]:
    """Regex search across files whose name matches file_pattern; returns file, line number and text."""

    try:
        base = _resolve(path)
        regex = re.compile(pattern)
    except (PermissionError, re.error) as exc:
        return _err(str(exc))
    hits = []
    for file in sorted(base.rglob("*")):
        if not file.is_file() or not fnmatch.fnmatch(file.name, file_pattern):
            continue
        try:
            for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
                if regex.search(line):
                    hits.append({"file": _rel(file), "line": number, "text": line.strip()})
        except UnicodeDecodeError:
            continue
    return _ok({"pattern": pattern, "file_pattern": file_pattern, "matches": hits, "count": len(hits)})


# ----------------------------------------------------------------------------- safety gate

SAFE_PREFIXES: tuple[str, ...] = (
    "ls", "pwd", "cat", "head", "tail", "wc", "grep", "find", "echo", "python3 --version",
    "git status", "git log", "git diff", "date", "whoami",
)

# Each pattern is matched against every segment of the command (split on ; && || | and newlines).
DESTRUCTIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("recursive deletion", re.compile(r"\brm\b.*\s(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b|\bfind\b.*\s-delete\b|"
                                      r"\bshred\b|\bgit\s+clean\b.*-[a-zA-Z]*f")),
    ("privilege escalation", re.compile(r"(^|\s)(sudo|doas|su)(\s|$)|\bpkexec\b")),
    ("permission/ownership change", re.compile(r"\b(chmod|chown|chgrp|chattr|setfacl)\b")),
    ("raw-device write", re.compile(r"\bdd\b.*\bof=/dev/|>\s*/dev/(sd|disk|nvme|hd|rdisk)|\bmkswap\b")),
    ("filesystem creation", re.compile(r"\bmkfs(\.\w+)?\b|\bnewfs\b|\bdiskutil\s+(erase|format)|\bfdisk\b|"
                                       r"\bparted\b")),
    # >, >>, >| (noclobber override), &>, and tee into an absolute path outside /tmp.
    ("redirection to a root path", re.compile(r"(&?>>?\|?|\btee(\s+-a)?)\s*/(?!tmp/|dev/null\b)[^\s]*")),
)
# Split on ; && || | newlines and command substitution - but not on the | of a ">|" redirect
# (v1 split there, which hid "echo x >| /etc/hosts" from the redirect check: a false allow).
SEGMENT_SPLIT = re.compile(r"\s*(?:;|&&|\|\||(?<!>)\||\n|`|\$\()\s*")


def is_destructive(command: str) -> bool:
    """True if any segment of the command matches the destructive deny-list."""

    return bool(destructive_reasons(command))


def destructive_reasons(command: str) -> list[str]:
    reasons = []
    for segment in [s for s in SEGMENT_SPLIT.split(command) if s.strip()]:
        for label, pattern in DESTRUCTIVE_PATTERNS:
            if pattern.search(segment) and label not in reasons:
                reasons.append(label)
    return reasons


def _matches_safe_prefix(command: str) -> bool:
    stripped = command.strip()
    return any(stripped == p or stripped.startswith(p + " ") for p in SAFE_PREFIXES)


def confirm_bash(command: str, auto_approve: bool = False) -> dict[str, Any]:
    """Allow/block decision with a short reason. The deny-list is checked before the allow-list."""

    if not command or not command.strip():
        return {"allowed": False, "reason": "empty command"}
    reasons = destructive_reasons(command)
    if reasons:
        if auto_approve:
            return {"allowed": True, "reason": f"destructive ({', '.join(reasons)}) but explicitly confirmed"}
        return {"allowed": False, "reason": f"blocked: destructive ({', '.join(reasons)}); needs confirmation"}
    if _matches_safe_prefix(command):
        return {"allowed": True, "reason": "matches SAFE_PREFIXES and is not destructive"}
    if auto_approve:
        return {"allowed": True, "reason": "not in SAFE_PREFIXES; explicitly confirmed"}
    return {"allowed": False, "reason": "blocked: not in SAFE_PREFIXES; needs confirmation"}


def bash(command: str, auto_approve: bool = False, timeout: int = 10) -> dict[str, Any]:
    """Run a command in the sandbox only if confirm_bash allows it."""

    decision = confirm_bash(command, auto_approve)
    if not decision["allowed"]:
        return {"ok": False, "data": {"gate": decision}, "error": decision["reason"]}
    if _SANDBOX is None:
        return _err("no sandbox set; call set_sandbox() first")
    try:
        completed = subprocess.run(shlex.split(command) if not re.search(r"[|;&<>]", command) else command,
                                   shell=bool(re.search(r"[|;&<>]", command)), cwd=_SANDBOX,
                                   capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return _err(str(exc))
    return _ok({"gate": decision, "returncode": completed.returncode,
                "stdout": completed.stdout[-2000:], "stderr": completed.stderr[-1000:]})


# ----------------------------------------------------------------------------- agent tool specs


def file_tool_specs() -> list[Any]:
    """The six tools as ToolSpecs for src.agent_loop.run_agent."""

    from src.agent_loop import ToolSpec

    def spec(name: str, description: str, properties: dict[str, Any], required: list[str], fn: Any) -> Any:
        return ToolSpec(name, description, {"type": "object", "properties": properties, "required": required,
                                            "additionalProperties": False}, lambda args: fn(**args))

    string = {"type": "string"}
    return [
        spec("glob_files", "List files matching a glob pattern, e.g. '**/*.py'.",
             {"pattern": string, "path": string}, ["pattern"], glob_files),
        spec("search_in_files", "Regex search inside files; file_pattern filters file names, e.g. '*.py'.",
             {"pattern": string, "path": string, "file_pattern": string}, ["pattern"], search_in_files),
        spec("read_file", "Read a file; max_lines limits how many lines are returned.",
             {"path": string, "max_lines": {"type": "integer", "minimum": 1}}, ["path"], read_file),
        spec("write_file", "Create or overwrite a file.", {"path": string, "content": string},
             ["path", "content"], write_file),
        spec("edit_file", "Replace one exact occurrence of old with new; returns a diff.",
             {"path": string, "old": string, "new": string}, ["path", "old", "new"], edit_file),
        spec("bash", "Run a shell command in the sandbox (guarded by the safety gate).",
             {"command": string}, ["command"], lambda command: bash(command)),
    ]
