#!/usr/bin/env python3
"""Five-turn (or interactive) chat demo with per-turn and cumulative token accounting."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from model_client import ModelClient  # noqa: E402


def load_system_prompt() -> str:
    return (ROOT / "AGENT.md").read_text()


def print_turn_tokens(result) -> None:
    print(
        f"[tokens] input={result.input_tokens}  "
        f"output={result.output_tokens}  total={result.total_tokens}"
    )


def print_stats(turn_count: int, in_tok: int, out_tok: int, history: list) -> None:
    serialized_len = len(json.dumps(history))
    print("--- /stats ---")
    print(f"turn_count: {turn_count}")
    print(f"cumulative_input_tokens: {in_tok}")
    print(f"cumulative_output_tokens: {out_tok}")
    print(f"cumulative_total_tokens: {in_tok + out_tok}")
    print(f"serialized_conversation_history_length: {serialized_len}")
    print("--------------")


def run_scripted() -> None:
    """Deterministic five-turn conversation for the HW1 report."""
    client = ModelClient()
    history = [{"role": "system", "content": load_system_prompt()}]
    in_tok = out_tok = 0
    turn_records = []
    stats_records = []
    turns = [
        "Review this function: def add(a,b): return a+b",
        "The function does not check types. What would you change?",
        "Rewrite the review for a version that adds logging of arguments.",
        "/stats",
        "Is logging user-controlled strings a security issue here?",
        "Give a final bullet-only verdict on shipping add().",
        "/stats",
    ]

    turn_count = 0
    print("Using system prompt from AGENT.md (bullet-only code review).")
    for item in turns:
        if item == "/stats":
            print_stats(turn_count, in_tok, out_tok, history)
            stats_records.append(
                {
                    "after_turn": turn_count,
                    "cumulative_input_tokens": in_tok,
                    "cumulative_output_tokens": out_tok,
                    "cumulative_total_tokens": in_tok + out_tok,
                    "serialized_conversation_history_length": len(
                        json.dumps(history)
                    ),
                }
            )
            continue
        turn_count += 1
        history.append({"role": "user", "content": item})
        print(f"\n=== turn {turn_count} user ===")
        print(item)
        result = client.complete(history, temperature=0.2)
        history.append({"role": "assistant", "content": result.text})
        in_tok += result.input_tokens
        out_tok += result.output_tokens
        turn_records.append(
            {
                "turn": turn_count,
                "user": item,
                "assistant": result.text,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
            }
        )
        print(f"=== turn {turn_count} assistant ===")
        print(result.text)
        print_turn_tokens(result)

    print("\n=== exit totals ===")
    print(f"cumulative_input_tokens: {in_tok}")
    print(f"cumulative_output_tokens: {out_tok}")
    print(f"cumulative_total_tokens: {in_tok + out_tok}")
    print(f"turn_count: {turn_count}")

    output_path = ROOT / "reports" / "hw01" / "raw" / "hw1_client_tokens.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "python_version": sys.version.split()[0],
        "model": client.model,
        "system_prompt_file": "AGENT.md",
        "turns": turn_records,
        "stats": stats_records,
        "totals": {
            "turn_count": turn_count,
            "cumulative_input_tokens": in_tok,
            "cumulative_output_tokens": out_tok,
            "cumulative_total_tokens": in_tok + out_tok,
        },
    }

    output_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"machine_readable_tokens: {output_path.relative_to(ROOT)}")


def run_interactive() -> None:
    client = ModelClient()
    history = [{"role": "system", "content": load_system_prompt()}]
    in_tok = out_tok = turn_count = 0
    print("hw1_client interactive mode. Commands: /stats  /exit")
    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            user = "/exit"
        if not user:
            continue
        if user == "/exit":
            print(
                f"exit input={in_tok} output={out_tok} total={in_tok + out_tok} turns={turn_count}"
            )
            break
        if user == "/stats":
            print_stats(turn_count, in_tok, out_tok, history)
            continue
        turn_count += 1
        history.append({"role": "user", "content": user})
        result = client.complete(history, temperature=0.2)
        history.append({"role": "assistant", "content": result.text})
        in_tok += result.input_tokens
        out_tok += result.output_tokens
        print(result.text)
        print_turn_tokens(result)


def main() -> int:
    if "--interactive" in sys.argv:
        run_interactive()
    else:
        run_scripted()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
