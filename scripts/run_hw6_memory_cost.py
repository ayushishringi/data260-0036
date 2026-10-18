"""Run HW6 memory-size and policy experiments against a running API."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
import uuid
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PROBES_PATH = ROOT / "memory_probes.yaml"
OUTPUT_PATH = ROOT / "reports" / "hw06" / "raw" / "memory_cost_comparison.json"

CONVERSATION = [
    "I am studying open-source package vulnerabilities.",
    "What is a CVE and why is it useful?",
    "How do dependency scanners find vulnerable packages?",
    "What is the difference between direct and transitive dependencies?",
    "How should vulnerabilities be prioritized?",
    "What is an SBOM?",
    "How does an SBOM support incident response?",
    "Why are transitive dependencies difficult to track?",
    "What is dependency confusion?",
    "How can teams reduce supply-chain risk?",
    "What does a lockfile do?",
    "Why should dependencies be pinned?",
    "What is the difference between severity and exploitability?",
    "How should a team respond to a critical CVE?",
    "What evidence should a vulnerability report contain?",
    "How can a team detect vulnerable packages in CI?",
    "What is the purpose of a software bill of materials?",
    "How can scanners produce false positives?",
    "Why should teams scan indirect dependencies?",
    "How does patching affect dependency trees?",
    "What is a vulnerability disclosure?",
    "Why are vulnerable packages sometimes hard to remove?",
    "How can a team prioritize many vulnerabilities?",
    "What should be documented after remediation?",
    "How can memory help answer these questions consistently?",
    "What is the role of a package maintainer?",
    "How do security advisories differ from CVEs?",
    "Why should dependency scans be repeated?",
    "What is the most important supply-chain lesson?",
    "Summarize the main ideas from this conversation.",
]


def post_chat(base_url: str, user_id: str, session_id: str, message: str) -> dict:
    payload = json.dumps({"user_id": user_id, "session_id": session_id, "message": message}).encode()
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.loads(response.read().decode())
    body.setdefault("usage", {})["wall_latency_ms"] = round(
        (time.perf_counter() - started) * 1000, 3
    )
    return body


def score_probe(reply: str, probe: dict) -> int:
    text = reply.lower()
    criteria = probe.get("expected_criteria", [])
    keyword_groups = {
        "mentions data-260": ["data-260", "data 260"],
        "mentions open-source package vulnerabilities": [
            "open-source package", "open source package", "vulnerabilit"
        ],
        "explains that cve is a standardized vulnerability identifier": [
            "common vulnerabilities and exposures", "standardized", "identifier"
        ],
        "mentions dependency trees": ["dependency tree", "dependency trees"],
        "mentions matching versions against vulnerability databases": [
            "version", "vulnerability database", "known vulnerabilit"
        ],
        "describes an inventory of software components": [
            "inventory", "components", "software bill of materials", "sbom"
        ],
        "connects the inventory to vulnerability response": [
            "vulnerability response", "incident response", "respond", "impact"
        ],
        "mentions severity or exploitability": ["severity", "exploitability"],
        "mentions affected scope or urgency": ["scope", "urgency", "priorit", "impact"],
    }
    hits = sum(
        1 for criterion in criteria
        if any(keyword in text for keyword in keyword_groups.get(criterion.lower(), [criterion.lower()]))
    )
    if not criteria or hits == 0:
        return 1
    if hits < len(criteria):
        return 3
    return 5


def run_setting(base_url: str, setting: str, policy: str, probes: list[dict]) -> dict:
    user_id = f"hw6-cost-{setting}-{policy}-{uuid.uuid4().hex[:8]}"
    session_id = f"session-{uuid.uuid4().hex[:8]}"
    turns = [post_chat(base_url, user_id, session_id, message) for message in CONVERSATION]
    probe_results = []
    for probe in probes:
        result = post_chat(base_url, user_id, session_id, probe["question"])
        probe_results.append({
            "id": probe["id"],
            "score": score_probe(result.get("reply", ""), probe),
            "usage": result.get("usage", {}),
        })
    usages = [turn.get("usage", {}) for turn in turns]
    return {
        "short_term_n": int(setting),
        "policy": policy,
        "user_id": user_id,
        "session_id": session_id,
        "conversation_turns": len(turns),
        "mean_prompt_tokens_per_turn": statistics.mean(
            usage.get("prompt_tokens", 0) for usage in usages
        ),
        "mean_latency_ms": statistics.mean(
            usage.get("latency_ms", usage.get("wall_latency_ms", 0)) for usage in usages
        ),
        "probe_quality_mean": statistics.mean(item["score"] for item in probe_results),
        "probe_results": probe_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8036")
    parser.add_argument("--settings", nargs="+", default=["4", "12", "30"])
    parser.add_argument("--policy", default="window")
    args = parser.parse_args()
    probes = yaml.safe_load(PROBES_PATH.read_text())["probes"]
    results = [run_setting(args.base_url, setting, args.policy, probes) for setting in args.settings]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"settings": results}, indent=2) + "\n")
    print(json.dumps({"output": str(OUTPUT_PATH), "settings": results}, indent=2))


if __name__ == "__main__":
    main()
