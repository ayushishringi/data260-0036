"""HW7 Part 2 (agent loop) and Part 3 (Reflexion) experiment runner.

  demo         run fixed tasks A, B, C once each plus the nonexistent-id error-recovery case
  reliability  N tool-use attempts across the three fixed cases (same model settings, per-attempt seed)
  reflexion    original loop vs Reflexion loop on the three fixed cases

Writes machine-readable results to reports/hw07/raw/.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent_loop import LOST_CHAIN, MALFORMED, TEXT_INSTEAD_OF_TOOL, UNKNOWN_TOOL, run_agent  # noqa: E402
from src.reflexion import run_with_reflexion, verify  # noqa: E402

RAW = ROOT / "reports" / "hw07" / "raw"
CASES_PATH = ROOT / "tests" / "fixtures" / "hw7" / "agent_cases.json"
SEED = 36
RELIABILITY_TEMPERATURE = 0.7


def load_cases() -> dict:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def banner(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}  ({datetime.now().isoformat(timespec='seconds')})\n{'=' * 78}", flush=True)


# ----------------------------------------------------------------------------- demo


def demo() -> None:
    data = load_cases()
    runs = []
    for case in data["cases"]:
        banner(f"Task {case['id']} ({case['kind']}): {case['prompt']}")
        result = run_agent(case["prompt"], run_id=f"demo-{case['id']}")
        verdict = verify(case, result)
        print(f"FINAL ANSWER: {result['final_answer']}")
        print(f"tools called: {' -> '.join(verdict['tools_called'])} | total tool calls: {result['total_tool_calls']}"
              f" | verifier: {'PASS' if verdict['passed'] else 'FAIL ' + str(verdict['failed_checks'])}")
        runs.append({"case_id": case["id"], "result": result, "verdict": verdict})

    case = data["error_recovery"]
    banner(f"Error recovery ({case['id']}): {case['prompt']}")
    result = run_agent(case["prompt"], run_id="demo-E")
    detail_calls = [s for s in result["trace"] if s["tool"] == "detail"]
    print(f"FINAL ANSWER: {result['final_answer']}")
    for step in detail_calls:
        print(f"execute_tool('detail', {json.dumps(step['inputs'])}) -> {json.dumps(step['observation'])}")
    handled = bool(detail_calls) and not detail_calls[0]["observation"]["ok"] and result["stop_reason"] == \
        "final_answer"
    print(f"handled without crashing: {handled} (stop_reason={result['stop_reason']})")
    runs.append({"case_id": "E", "result": result, "handled_without_crash": handled})
    (RAW / "agent_demo_runs.json").write_text(json.dumps(runs, indent=2, default=str) + "\n")
    print(f"\nwrote {(RAW / 'agent_demo_runs.json').relative_to(ROOT)}")


# ----------------------------------------------------------------------------- repair-path demo


class CorruptingClient:
    """Fault injection for evidence only: corrupts the model's Nth tool call, then passes everything through."""

    def __init__(self, corrupt: str, at_call: int = 1) -> None:
        from src.model_client import ModelClient
        self.inner, self.corrupt, self.at_call, self.calls_seen = ModelClient(), corrupt, at_call, 0

    def complete(self, messages, **kwargs):
        result = self.inner.complete(messages, **kwargs)
        calls = result.raw.get("message", {}).get("tool_calls") or []
        if calls:
            self.calls_seen += 1
            if self.calls_seen == self.at_call:
                function = calls[0]["function"]
                if self.corrupt == "unknown_tool":
                    print(f"   [fault injection] renaming tool '{function['name']}' -> 'get_vulnerability'")
                    function["name"] = "get_vulnerability"
                else:
                    print(f"   [fault injection] turning integer id into a string in {function['arguments']}")
                    function["arguments"] = {k: str(v) for k, v in function["arguments"].items()}
        return result


def repair_demo() -> None:
    case = load_cases()["cases"][0]
    for corrupt, at_call in (("unknown_tool", 1), ("string_id", 2)):
        banner(f"Repair-path demo (fault injection: {corrupt} on model tool call #{at_call}) - task A")
        result = run_agent(case["prompt"], client=CorruptingClient(corrupt, at_call), run_id=f"repair-{corrupt}")
        verdict = verify(case, result)
        print(f"repairs: {[r['category'] + ': ' + r['problem'] for r in result['repairs']]}")
        print(f"FINAL ANSWER: {result['final_answer']}")
        print(f"stop_reason={result['stop_reason']} verifier={'PASS' if verdict['passed'] else 'FAIL'}")


# ----------------------------------------------------------------------------- reliability


def classify(result: dict, verdict: dict) -> dict:
    """Per-attempt call accounting for the before/after-repair rates."""

    emitted = result["emitted_calls"]
    failures = [c for c in emitted if not c["ok"]]
    # A failed call is recovered when a later turn in the same run produced a well-formed call.
    last_valid_iteration = max((c["iteration"] for c in emitted if c["ok"]), default=0)
    unrecovered = [c for c in failures if c["iteration"] >= last_valid_iteration
                   or result["stop_reason"] == "repair_limit"]
    valid = len(emitted) - len(failures)
    categories = Counter(c["category"] for c in failures)
    if verdict["lost_chain"]:
        categories[LOST_CHAIN] += 1
    return {"emitted": len(emitted), "valid": valid, "failures": len(failures), "unrecovered": len(unrecovered),
            "categories": dict(categories)}


def reliability(attempts: int) -> None:
    cases = load_cases()["cases"]
    banner(f"Reliability: {attempts} attempts across cases A/B/C, temperature={RELIABILITY_TEMPERATURE}, "
           f"seed = {SEED}*1000 + attempt")
    rows = []
    for index in range(attempts):
        case = cases[index % len(cases)]
        seed = SEED * 1000 + index
        print(f"\n--- attempt {index + 1}/{attempts}: case {case['id']} seed={seed}", flush=True)
        result = run_agent(case["prompt"], temperature=RELIABILITY_TEMPERATURE, seed=seed,
                           run_id=f"rel-{index + 1:02d}-{case['id']}")
        verdict = verify(case, result)
        counts = classify(result, verdict)
        rows.append({
            "attempt": index + 1, "case_id": case["id"], "seed": seed, "stop_reason": result["stop_reason"],
            "tool_calls": result["total_tool_calls"], "emitted_calls": counts["emitted"],
            "skipped_parallel_calls": result["skipped_parallel_calls"],
            "well_formed_calls": counts["valid"], "failed_calls": counts["failures"],
            "unrecovered_calls": counts["unrecovered"], "repairs": len(result["repairs"]),
            "malformed_arguments": counts["categories"].get(MALFORMED, 0),
            "unknown_tool": counts["categories"].get(UNKNOWN_TOOL, 0),
            "text_when_tool_required": counts["categories"].get(TEXT_INSTEAD_OF_TOOL, 0),
            "lost_multi_step_chain": counts["categories"].get(LOST_CHAIN, 0),
            "first_try_clean": counts["failures"] == 0,
            "completed_after_repair": result["stop_reason"] == "final_answer" and counts["unrecovered"] == 0,
            "verifier_passed": verdict["passed"], "failed_checks": ";".join(verdict["failed_checks"]),
            "tokens": result["tokens"]["input"] + result["tokens"]["output"], "latency_ms": result["latency_ms"],
            "tools_called": " > ".join(verdict["tools_called"]),
            "repair_problems": " | ".join(f"{r['category']}: {r['problem']}" for r in result["repairs"]),
        })
        print(f"attempt {index + 1}: verifier={'PASS' if verdict['passed'] else 'FAIL'} "
              f"repairs={len(result['repairs'])} lost_chain={verdict['lost_chain']}", flush=True)

    with (RAW / "reliability_attempts.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    total_emitted = sum(r["emitted_calls"] for r in rows)
    total_valid = sum(r["well_formed_calls"] for r in rows)
    total_unrecovered = sum(r["unrecovered_calls"] for r in rows)
    summary = {
        "attempts": len(rows),
        "model": "qwen3:4b (Ollama)", "temperature": RELIABILITY_TEMPERATURE, "num_ctx": 16384,
        "seed_rule": f"{SEED}*1000 + attempt index",
        "call_level": {
            "emitted_calls": total_emitted,
            "well_formed_before_repair": round(total_valid / total_emitted, 4) if total_emitted else None,
            "well_formed_after_repair": round(total_valid / (total_valid + total_unrecovered), 4)
            if total_valid + total_unrecovered else None,
        },
        "attempt_level": {
            "clean_before_repair": round(sum(r["first_try_clean"] for r in rows) / len(rows), 4),
            "completed_after_repair": round(sum(r["completed_after_repair"] for r in rows) / len(rows), 4),
            "verifier_pass_rate": round(sum(r["verifier_passed"] for r in rows) / len(rows), 4),
        },
        "failures_by_type": {key: sum(r[key] for r in rows) for key in
                             ("malformed_arguments", "unknown_tool", "text_when_tool_required",
                              "lost_multi_step_chain")},
        "by_case": {cid: {"attempts": sum(r["case_id"] == cid for r in rows),
                          "verifier_passed": sum(r["verifier_passed"] for r in rows if r["case_id"] == cid)}
                    for cid in ("A", "B", "C")},
        "mean_tool_calls": round(statistics.mean(r["tool_calls"] for r in rows), 2),
        "mean_latency_ms": round(statistics.mean(r["latency_ms"] for r in rows), 1),
    }
    (RAW / "reliability_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    banner("Reliability summary")
    print(json.dumps(summary, indent=2))


# ----------------------------------------------------------------------------- reflexion comparison


def reflexion(runs_per_case: int, temperature: float = RELIABILITY_TEMPERATURE, label: str = "",
              outage_attempts: int = 0) -> None:
    cases = load_cases()["cases"]
    banner(f"Original loop vs Reflexion: {runs_per_case} runs per case, temperature={temperature}, "
           f"detail outage during first {outage_attempts} attempt(s)")
    records = []
    for case in cases:
        for index in range(runs_per_case):
            seed = SEED * 1000 + 500 + index
            print(f"\n--- case {case['id']} run {index + 1}/{runs_per_case} seed={seed}", flush=True)
            outcome = run_with_reflexion(case, temperature=temperature, seed=seed, user_id="s0036",
                                         outage_attempts=outage_attempts)
            first = outcome["attempts"][0]
            final = outcome["attempts"][-1]
            records.append({
                "case_id": case["id"], "run": index + 1, "seed": seed, "run_id": outcome["run_id"],
                # Original loop = attempt 0 alone (a plain Part 2 run_agent call, no reflection).
                "original": {
                    "success": first["verdict"]["passed"],
                    "unsupported_claims": len(first["verdict"]["unsupported_claims"]),
                    "tool_calls": first["result"]["total_tool_calls"],
                    "tokens": first["result"]["tokens"]["input"] + first["result"]["tokens"]["output"],
                    "latency_ms": first["result"]["latency_ms"],
                    "verifier_false_rejection_candidate": (not first["verdict"]["passed"]) and first["oracle_accepts"],
                    "failed_checks": first["verdict"]["failed_checks"],
                    "final_answer": first["result"]["final_answer"],
                },
                "reflexion": {
                    "success": outcome["success"], "stop_reason": outcome["stop_reason"],
                    "retries": outcome["retries"],
                    "unsupported_claims": len(final["verdict"]["unsupported_claims"]),
                    "tool_calls": outcome["tool_calls"], "tokens": outcome["tokens"],
                    "latency_ms": outcome["latency_ms"],
                    "verifier_false_rejection_candidates": sum(
                        (not a["verdict"]["passed"]) and a["oracle_accepts"] for a in outcome["attempts"]),
                    "final_answer": final["result"]["final_answer"],
                    "attempt_failed_checks": [a["verdict"]["failed_checks"] for a in outcome["attempts"]],
                    "reflections": [a["reflection"]["reflection"] for a in outcome["attempts"] if a["reflection"]],
                },
            })
            with (RAW / f"reflexion_runs{label}.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(records[-1], default=str) + "\n")
    summarize_reflexion(records, temperature, label, outage_attempts)


def summarize_reflexion(records: list[dict], temperature: float, label: str = "", outage_attempts: int = 0) -> dict:
    def block(key: str) -> dict:
        items = [r[key] for r in records]
        return {
            "runs": len(items),
            "task_success": round(sum(i["success"] for i in items) / len(items), 4),
            "unsupported_claims_total": sum(i["unsupported_claims"] for i in items),
            "retry_rate": round(sum(i.get("retries", 0) > 0 for i in items) / len(items), 4),
            "mean_tool_calls": round(statistics.mean(i["tool_calls"] for i in items), 2),
            "mean_tokens": round(statistics.mean(i["tokens"] for i in items), 1),
            "mean_latency_ms": round(statistics.mean(i["latency_ms"] for i in items), 1),
            "verifier_false_rejection_candidates": sum(
                i.get("verifier_false_rejection_candidate", 0) or i.get("verifier_false_rejection_candidates", 0)
                for i in items),
        }

    summary = {"temperature": temperature, "runs_per_case": len(records) // 3,
               "condition": f"detail outage during first {outage_attempts} attempt(s)" if outage_attempts
               else "no fault injection",
               "original_loop": block("original"), "reflexion_loop": block("reflexion"),
               "reflexion_stop_reasons": dict(Counter(r["reflexion"]["stop_reason"] for r in records)),
               "by_case": {cid: {"original_success": sum(r["original"]["success"] for r in records
                                                         if r["case_id"] == cid),
                                 "reflexion_success": sum(r["reflexion"]["success"] for r in records
                                                          if r["case_id"] == cid),
                                 "runs": sum(r["case_id"] == cid for r in records)}
                          for cid in ("A", "B", "C")}}
    (RAW / f"reflexion_comparison{label}.json").write_text(json.dumps(summary, indent=2) + "\n")
    banner("Original vs Reflexion summary")
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo")
    sub.add_parser("repair-demo")
    rel = sub.add_parser("reliability")
    rel.add_argument("--attempts", type=int, default=21)
    ref = sub.add_parser("reflexion")
    ref.add_argument("--runs-per-case", type=int, default=4)
    ref.add_argument("--temperature", type=float, default=RELIABILITY_TEMPERATURE)
    ref.add_argument("--label", default="", help="suffix for output files, e.g. _t1.0")
    ref.add_argument("--outage-attempts", type=int, default=0,
                     help="fault injection: detail() times out during the first N attempts")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    if args.command == "demo":
        demo()
    elif args.command == "repair-demo":
        repair_demo()
    elif args.command == "reliability":
        reliability(args.attempts)
    else:
        (RAW / f"reflexion_runs{args.label}.jsonl").unlink(missing_ok=True)
        reflexion(args.runs_per_case, args.temperature, args.label, args.outage_attempts)


if __name__ == "__main__":
    main()
