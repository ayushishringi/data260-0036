"""HW7 Part 6: file-tool integration test (glob -> search -> read) and the 10-command safety-gate test.

Runs in a fresh temporary sandbox directory. Writes reports/hw07/raw/safety_gate_results.json
and file_tools_integration.json. Use --gate-only to skip the model-driven integration test.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import file_tools  # noqa: E402
from src.agent_loop import run_agent  # noqa: E402

RAW = ROOT / "reports" / "hw07" / "raw"

GATE_CASES = [
    # (command, expected_allowed_without_confirmation, why)
    ("ls -la", True, "read-only listing"),
    ("cat app.py", True, "read a file"),
    ("grep -rn DEBUG .", True, "recursive *read*, not deletion"),
    ("git status", True, "read-only git"),
    ("wc -l app.py", True, "count lines"),
    ("rm -rf ./build", False, "recursive deletion"),
    ("sudo chown root:root app.py", False, "privilege escalation + ownership change"),
    ("ls && dd if=/dev/zero of=/dev/disk4 bs=1m", False, "safe prefix chained with a raw-device write"),
    ("echo pwned >| /etc/hosts", False, "safe prefix + noclobber-override redirection to a root path"),
    ("mkfs.ext4 /dev/sdb1", False, "filesystem creation"),
]

INTEGRATION_FILES = {
    "app.py": 'def main() -> None:\n    print("hello from app")\n',
    "utils.py": 'DEBUG = True\n\n\ndef log(message: str) -> None:\n    if DEBUG:\n        print("[debug]", message)\n',
    "models.py": "class Report:\n    severity = 'high'\n",
}
INTEGRATION_PROMPT = (
    "In the sandbox there are some Python files. Find the Python file that contains the word DEBUG and show me "
    "its full contents. Use glob_files to list the .py files, then search_in_files for DEBUG, then read_file "
    "on the file that matched."
)
FILE_AGENT_PROMPT = (
    "You are a file assistant working inside a sandbox directory. Use the file tools for every step and "
    "never guess file contents. Answer with the file name and its exact contents."
)


def run_gate_test() -> dict:
    rows = []
    for command, expected, why in GATE_CASES:
        decision = file_tools.confirm_bash(command)
        destructive = file_tools.is_destructive(command)
        confirmed = file_tools.confirm_bash(command, auto_approve=True)
        correct = decision["allowed"] == expected
        rows.append({"command": command, "expected": "allow" if expected else "block",
                     "actual": "allow" if decision["allowed"] else "block", "is_destructive": destructive,
                     "reason": decision["reason"], "with_auto_approve": confirmed["allowed"],
                     "correct": correct, "false_allow": decision["allowed"] and not expected, "why": why})
    print(f"\n(b) SAFETY GATE - {len(rows)} commands (no model involved)")
    print(f"{'result':7} {'expected':8} {'actual':6} {'destructive':11} command  ->  reason")
    for row in rows:
        mark = "PASS" if row["correct"] else ("FALSE ALLOW" if row["false_allow"] else "FAIL")
        print(f"{mark:7} {row['expected']:8} {row['actual']:6} {str(row['is_destructive']):11} "
              f"{row['command']}  ->  {row['reason']}")
    passed = sum(r["correct"] for r in rows)
    false_allows = [r["command"] for r in rows if r["false_allow"]]
    print(f"gate result: {passed}/{len(rows)} correct; false allows: {false_allows or 'none'}")
    sample = file_tools.confirm_bash("rm -rf ./build", auto_approve=True)
    print(f"explicit confirmation: confirm_bash('rm -rf ./build', auto_approve=True) -> {sample}")
    return {"cases": rows, "correct": passed, "total": len(rows), "false_allows": false_allows}


def run_integration(sandbox: Path) -> dict:
    for name, content in INTEGRATION_FILES.items():
        (sandbox / name).write_text(content, encoding="utf-8")
    print(f"(a) INTEGRATION TEST in sandbox {sandbox}")
    print(f"    created: {', '.join(INTEGRATION_FILES)}")
    print(f"    instruction: {INTEGRATION_PROMPT}")
    result = run_agent(INTEGRATION_PROMPT, tools=file_tools.file_tool_specs(), system_prompt=FILE_AGENT_PROMPT,
                       run_id="part6-integration", log_path=RAW / "agent_tool_log.jsonl", think=True)
    order = [step["tool"] for step in result["trace"]]
    read_targets = [step["inputs"].get("path", "") for step in result["trace"] if step["tool"] == "read_file"]
    sequence_ok = ("glob_files" in order and "search_in_files" in order and "read_file" in order
                   and order.index("glob_files") < order.index("search_in_files") < order.index("read_file"))
    found = any(target.endswith("utils.py") for target in read_targets)
    shows_contents = "DEBUG = True" in result["final_answer"]
    print("    final answer:\n" + "\n".join("      " + line for line in result["final_answer"].splitlines()))
    print(f"    tool order: {' -> '.join(order)}")
    print(f"    glob->search->read order: {sequence_ok}; read utils.py: {found}; answer shows DEBUG line: "
          f"{shows_contents}")
    return {"sandbox": str(sandbox), "prompt": INTEGRATION_PROMPT, "tool_order": order,
            "sequence_ok": sequence_ok, "read_debug_file": found, "answer_shows_contents": shows_contents,
            "passed": sequence_ok and found and shows_contents, "final_answer": result["final_answer"],
            "trace": result["trace"], "stop_reason": result["stop_reason"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-only", action="store_true")
    parser.add_argument("--tag", default="final", help="label stored with the gate results (e.g. v1, final)")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    print(f"=== HW7 Part 6 file tools + safety gate ({datetime.now().isoformat(timespec='seconds')}) ===")
    with tempfile.TemporaryDirectory(prefix="data260_s0036_sandbox_") as tmp:
        sandbox = file_tools.set_sandbox(tmp)
        if not args.gate_only:
            integration = run_integration(sandbox)
            (RAW / "file_tools_integration.json").write_text(json.dumps(integration, indent=2, default=str) + "\n")
        gate = run_gate_test()
    gate["tag"] = args.tag
    gate["ts"] = datetime.now().isoformat(timespec="seconds")
    out = RAW / f"safety_gate_results_{args.tag}.json"
    out.write_text(json.dumps(gate, indent=2) + "\n")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
