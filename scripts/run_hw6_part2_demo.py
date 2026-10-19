"""HW6 Part 2 demo: send 12 messages in one session to POST /api/chat.

Saves every full response to reports/hw06/raw/part2_demo_chat.json and prints a
compact transcript showing the reply plus what memory each turn used.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "hw06" / "raw" / "part2_demo_chat.json"
BASE_URL = "http://127.0.0.1:8036"
USER_ID = sys.argv[1] if len(sys.argv) > 1 else "ayushi_demo"
SESSION_ID = sys.argv[2] if len(sys.argv) > 2 else "demo_session_1"

MESSAGES = [
    "Hi, I am Ayushi and I am auditing open-source packages for my DATA-260 project.",
    "The package I am auditing is left-pad-plus version 3.4.1.",
    "What is a CVE in one sentence?",
    "Our deadline for fixing critical CVEs is 9 days.",
    "How do dependency scanners find vulnerable packages?",
    "My reviewer is Dr. Okafor and she wants findings in CycloneDX format.",
    "What is a transitive dependency?",
    "We found that urllib-lite 0.9.2 is vulnerable and fetchkit pulls it in.",
    "How should I prioritize that finding?",
    "What does a lockfile do?",
    "Which package and version am I auditing?",
    "Who is my reviewer and what format does she want?",
]


def post(message: str) -> dict:
    payload = json.dumps({"user_id": USER_ID, "session_id": SESSION_ID, "message": message}).encode()
    request = urllib.request.Request(
        f"{BASE_URL}/api/chat", data=payload, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(response.read().decode())


def main() -> None:
    turns = []
    for index, message in enumerate(MESSAGES, start=1):
        body = post(message)
        turns.append({"message": message, "response": body})
        used = body["used"]
        summary = used.get("long_term_summary")
        print(f"[{index:2d}] USER: {message}")
        reply = " ".join(body["reply"].split())
        print(f"     ASSISTANT: {reply[:260]}{'...' if len(reply) > 260 else ''}")
        facts = "; ".join(f"{item['fact']} (imp {item['importance']}, sim {item['similarity']:.2f})"
                          for item in used["episodic_facts"])
        print(f"     used: short_term={used['short_term_message_count']} msgs | "
              f"summary={'yes (' + summary['scope'] + ')' if summary else 'none'} | "
              f"prompt_tokens={body['usage']['prompt_tokens']}")
        print(f"     episodic: {facts or '(none)'}", flush=True)
    OUTPUT.write_text(json.dumps({"user_id": USER_ID, "session_id": SESSION_ID, "turns": turns},
                                 indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
