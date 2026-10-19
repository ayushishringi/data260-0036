"""Run HW6 Part 3 memory-size and policy experiments.

For every configuration this script starts a fresh uvicorn server with
SHORT_TERM_N / MEMORY_POLICY set in its environment (the server reads them at
import time), checks that /api/chat reports the same config back, runs the
30-message conversation plus the five probes in a fresh session, then stops
the server. The port must be free before running.

Usage:
  .venv/bin/python scripts/run_hw6_memory_cost.py \
      --configs 4:window 12:window 30:window 12:compressed_window
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import statistics
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PROBES_PATH = ROOT / "memory_probes.yaml"
RAW = ROOT / "reports" / "hw06" / "raw"
OUTPUT_PATH = RAW / "memory_cost_comparison.json"
TURNS_CSV = RAW / "per_turn_tokens.csv"
INPUT_PRICE_PER_M = 1.0
OUTPUT_PRICE_PER_M = 5.0
CONVERSATIONS = 10_000

# Turns 2, 9, 17, 23 and 27 plant the facts asked about by memory_probes.yaml.
CONVERSATION = [
    "I am working on a vulnerability audit for my DATA-260 project.",
    "The package I am auditing is left-pad-plus version 3.4.1.",
    "What is a CVE and why is it useful?",
    "How do dependency scanners find vulnerable packages?",
    "What is the difference between direct and transitive dependencies?",
    "How should vulnerabilities be prioritized?",
    "What is an SBOM?",
    "How does an SBOM support incident response?",
    "Our internal deadline for fixing critical CVEs is 9 days, and our ticket queue is called SEC-ORCHID.",
    "Why are transitive dependencies difficult to track?",
    "What is dependency confusion?",
    "How can teams reduce supply-chain risk?",
    "What does a lockfile do?",
    "Why should dependencies be pinned?",
    "What is the difference between severity and exploitability?",
    "How should a team respond to a critical CVE?",
    "My reviewer is Dr. Okafor, and she wants all findings in CycloneDX format.",
    "What evidence should a vulnerability report contain?",
    "How can a team detect vulnerable packages in CI?",
    "How can scanners produce false positives?",
    "Why should teams scan indirect dependencies?",
    "How does patching affect dependency trees?",
    "The vulnerable transitive dependency we found is urllib-lite 0.9.2, pulled in by fetchkit.",
    "What is a vulnerability disclosure?",
    "Why are vulnerable packages sometimes hard to remove?",
    "How can a team prioritize many vulnerabilities?",
    "I scheduled the remediation demo for Thursday at 3 pm in room ENG-189.",
    "What should be documented after remediation?",
    "How do security advisories differ from CVEs?",
    "Why should dependency scans be repeated?",
]
assert len(CONVERSATION) == 30

HEDGE_WORDS = ("not sure", "i think", "may be", "might be", "possibly", "unclear")
UNKNOWN_WORDS = (
    "don't know", "do not know", "don't have", "do not have", "not mentioned",
    "no record", "not provided", "haven't mentioned", "not available", "no information",
)


def port_is_free(port: int) -> bool:
    # Bind test rather than connect: the HW2 Docker stack listens on *:8036, but
    # uvicorn can still bind 127.0.0.1:8036, which then takes precedence locally.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # same as uvicorn
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def start_server(port: int, short_term_n: int, policy: str, log_path: Path) -> subprocess.Popen:
    if not port_is_free(port):
        raise SystemExit(f"Port {port} is in use; stop the running API first.")
    env = {**os.environ, "SHORT_TERM_N": str(short_term_n), "MEMORY_POLICY": policy}
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 90
    while time.time() < deadline:
        # Require our JSON health body: Docker's nginx on *:8036 answers 200 with HTML
        # until uvicorn has bound 127.0.0.1.
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
                if json.loads(response.read().decode()).get("status") == "ok":
                    return process
        except (OSError, ValueError):
            pass
        time.sleep(1)
    process.terminate()
    raise SystemExit(f"Server did not start; see {log_path}")


def stop_server(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()


def post_chat(base_url: str, user_id: str, session_id: str, message: str) -> dict:
    payload = json.dumps({"user_id": user_id, "session_id": session_id, "message": message}).encode()
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=600) as response:
        body = json.loads(response.read().decode())
    body.setdefault("usage", {})["wall_latency_ms"] = round(
        (time.perf_counter() - started) * 1000, 3
    )
    return body


def score_probe(reply: str, probe: dict) -> int:
    """Apply the 1-5 rubric in memory_probes.yaml to one reply."""

    text = reply.casefold()
    criteria = probe["expected_criteria"]
    hits = sum(1 for criterion in criteria if any(word in text for word in criterion["any_of"]))
    if hits == len(criteria):
        return 4 if any(word in text for word in HEDGE_WORDS) else 5
    if hits:
        return 3
    return 2 if any(word in text for word in UNKNOWN_WORDS) else 1


def cost(input_tokens: float, output_tokens: float) -> dict:
    input_cost = input_tokens * CONVERSATIONS * INPUT_PRICE_PER_M / 1_000_000
    output_cost = output_tokens * CONVERSATIONS * OUTPUT_PRICE_PER_M / 1_000_000
    return {
        "input_cost_usd": round(input_cost, 2),
        "output_cost_usd": round(output_cost, 2),
        "total_cost_usd": round(input_cost + output_cost, 2),
    }


def run_config(port: int, short_term_n: int, policy: str, probes: list[dict], writer: csv.DictWriter) -> dict:
    label = f"N={short_term_n},{policy}"
    log_path = RAW / f"server_{short_term_n}_{policy}.log"
    process = start_server(port, short_term_n, policy, log_path)
    base_url = f"http://127.0.0.1:{port}"
    user_id = f"hw6-cost-{short_term_n}-{policy}-{uuid.uuid4().hex[:8]}"
    session_id = f"session-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        turns = []
        for index, message in enumerate(CONVERSATION, start=1):
            body = post_chat(base_url, user_id, session_id, message)
            usage = body["usage"]
            config = usage.get("config", {})
            if config.get("short_term_n") != short_term_n or config.get("memory_policy") != policy:
                raise SystemExit(f"{label}: server reported config {config}; aborting")
            turns.append(usage)
            components = usage["component_token_estimates"]
            writer.writerow({
                "setting": label, "kind": "conversation", "turn": index,
                "prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"],
                "latency_ms": usage["latency_ms"], **components,
                "short_term_message_count": body["used"]["short_term_message_count"],
            })
            print(f"[{datetime.now():%H:%M:%S}] {label} turn {index:2d}: prompt={usage['prompt_tokens']} "
                  f"completion={usage['completion_tokens']} latency_ms={usage['latency_ms']:.0f}", flush=True)
        probe_results = []
        for probe in probes:
            body = post_chat(base_url, user_id, session_id, probe["question"])
            usage = body["usage"]
            score = score_probe(body.get("reply", ""), probe)
            probe_results.append({
                "id": probe["id"],
                "planted_at_turn": probe["planted_at_turn"],
                "question": probe["question"],
                "score": score,
                "reply": body.get("reply", ""),
                "episodic_facts_used": [item["fact"] for item in body["used"]["episodic_facts"]],
                "usage": usage,
            })
            writer.writerow({
                "setting": label, "kind": probe["id"], "turn": "",
                "prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"],
                "latency_ms": usage["latency_ms"], **usage["component_token_estimates"],
                "short_term_message_count": body["used"]["short_term_message_count"],
            })
            print(f"[{datetime.now():%H:%M:%S}] {label} {probe['id']}: score={score}", flush=True)
    finally:
        stop_server(process)

    input_tokens = sum(turn["prompt_tokens"] for turn in turns)
    output_tokens = sum(turn["completion_tokens"] for turn in turns)
    return {
        "setting": label,
        "short_term_n": short_term_n,
        "policy": policy,
        "user_id": user_id,
        "session_id": session_id,
        "started_at": started_at,
        "conversation_turns": len(turns),
        "mean_prompt_tokens_per_turn": round(statistics.mean(turn["prompt_tokens"] for turn in turns), 2),
        "mean_short_term_window_tokens": round(
            statistics.mean(turn["component_token_estimates"]["short_term_window"] for turn in turns), 2
        ),
        "mean_completion_tokens_per_turn": round(statistics.mean(turn["completion_tokens"] for turn in turns), 2),
        "mean_latency_ms": round(statistics.mean(turn["latency_ms"] for turn in turns), 2),
        "conversation_input_tokens": input_tokens,
        "conversation_output_tokens": output_tokens,
        "cost_10k_conversations": cost(input_tokens, output_tokens),
        "probe_quality_mean": statistics.mean(item["score"] for item in probe_results),
        "probe_results": probe_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8036)
    parser.add_argument(
        "--configs", nargs="+", default=["4:window", "12:window", "30:window", "12:compressed_window"],
        help="SHORT_TERM_N:MEMORY_POLICY pairs",
    )
    args = parser.parse_args()
    probes = yaml.safe_load(PROBES_PATH.read_text())["probes"]
    RAW.mkdir(parents=True, exist_ok=True)
    fields = [
        "setting", "kind", "turn", "prompt_tokens", "completion_tokens", "latency_ms",
        "system_primer", "file_memory", "long_term_summary", "short_term_window", "episodic_facts",
        "short_term_message_count",
    ]
    results = []
    with TURNS_CSV.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for config in args.configs:
            short_term_n, policy = config.split(":")
            results.append(run_config(args.port, int(short_term_n), policy, probes, writer))
            stream.flush()
            OUTPUT_PATH.write_text(json.dumps({
                "experiment": {
                    "conversation_turns": len(CONVERSATION),
                    "probe_count": len(probes),
                    "model": os.getenv("OLLAMA_MODEL", "qwen3:4b"),
                    "ollama_num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "16384")),
                    "ollama_seed": int(os.getenv("OLLAMA_SEED", "36")),
                    "input_price_per_million": INPUT_PRICE_PER_M,
                    "output_price_per_million": OUTPUT_PRICE_PER_M,
                    "conversations_costed": CONVERSATIONS,
                },
                "settings": results,
            }, indent=2) + "\n")
    summary = [{k: v for k, v in item.items() if k != "probe_results"} for item in results]
    print(json.dumps({"output": str(OUTPUT_PATH), "settings": summary}, indent=2))


if __name__ == "__main__":
    main()
