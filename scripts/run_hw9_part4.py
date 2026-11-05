"""HW9 Part 4: run the self-improving Answering/Evaluator system.

Phases (default: all, in this order):
  controlled  4.1  one question whose initial answer is deliberately incomplete -> feedback -> revision
  train       4.2  training_data.json with repair + lesson creation (lessons appear after repeated failures
                   and are reloaded for later related questions) -> raw/part4_lessons_candidates.json
  validate    4.3  validation_data.json before/after each candidate lesson; keep only non-regressing
                   lessons -> data/hw9/lessons.json, decisions -> raw/part4_validation.json
  reuse       4.2  a later related question with the kept lessons loaded
  test        4.4  test_data.json on Baseline, Evaluator Repair, Lesson Memory, Validated Improvement
The test set is only used in the test phase and never creates or changes lessons.

Usage: make part4-hw09     (or: python scripts/run_hw9_part4.py --phases test)
"""

from __future__ import annotations

import argparse
import getpass
import json
import shutil
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.self_improving import DATA, LessonStore, SelfImprovingSystem, load_json, summarize  # noqa: E402

RAW = ROOT / "reports" / "hw09" / "raw"
CANDIDATES = RAW / "part4_lessons_candidates.json"
LESSONS = DATA / "lessons.json"
SCRATCH = RAW / "part4_scratch_lessons.json"
CONTROLLED = {"id": "controlled_01", "question": "Which version of lodash fixes CVE-2021-23337?"}
REUSE = {"id": "reuse_01", "question": "Which version of ws fixes the header-count denial of service?"}
PHASES = ["controlled", "train", "validate", "reuse", "test"]


def log(event: str, **fields: Any) -> None:
    detail = " ".join(f"{k}={json.dumps(v, default=str)}" for k, v in fields.items())
    print(f"{datetime.now().isoformat(timespec='seconds')} [part4] {event} {detail}", flush=True)


def save(name: str, payload: Any) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / name).write_text(json.dumps(payload, indent=2, default=str) + "\n")


def run_items(system: SelfImprovingSystem, items: list[dict]) -> list[dict]:
    results = []
    for item in items:
        result = system.solve(item)
        results.append(result)
        log("DONE", id=item["id"], attempts=result["n_attempts"], initial=result["initial_result"],
            final=result["final_result"], lessons=result["lessons_loaded"], latency_ms=result["latency_ms"])
    return results


def print_trace(result: dict) -> None:
    print(f"\nQuestion: {result['question']}")
    for attempt in result["attempts"]:
        label = "Initial answer" if attempt["attempt"] == 1 else "Revised answer"
        print(f"\n[{label} - attempt {attempt['attempt']}]{' (controlled fault: ' + attempt['fault'] + ')' if attempt.get('fault') else ''}")
        print(attempt["answer"])
        if attempt.get("lookup") is not None:
            print(f"  advisory lookup used: {attempt['lookup'] or 'no record'}")
        ev = attempt["evaluation"]
        print(f"[Evaluator] result={ev['result']}  explanation: {ev['explanation']}")
        if ev["feedback"]:
            print(f"[Evaluator] feedback: {ev['feedback']}")
    print(f"\nAttempts: {result['n_attempts']}   Final evaluation: {result['final_result']}")
    print(f"Final response: {result['final_answer']}")


# ----------------------------------------------------------------------------- phases


def controlled() -> None:
    print("\n=== 4.1 Controlled revision case ===")
    system = SelfImprovingSystem(repair=True, log=log)
    result = system.solve(CONTROLLED, fault="incomplete")
    print_trace(result)
    save("part4_controlled.json", result)


def train() -> None:
    print("\n=== 4.2 Training run (repair + lesson creation) ===")
    CANDIDATES.unlink(missing_ok=True)
    store = LessonStore(CANDIDATES)
    system = SelfImprovingSystem(repair=True, lessons=store, learn=True, log=log)
    results = run_items(system, load_json(DATA / "training_data.json"))
    save("part4_training.json", {"summary": summarize(results), "pattern_counts": dict(system.pattern_counts),
                                 "lessons": store.lessons, "results": results})
    print(f"candidate lessons: {[x['lesson_id'] + ' ' + x['pattern_key'] for x in store.lessons]}")


def compare(before: list[dict], after: list[dict]) -> dict:
    """The three keep conditions of 4.3, on initial answers (what a lesson changes) and final answers."""

    def ids(rows: list[dict], key: str, value: str) -> set[str]:
        return {r["id"] for r in rows if r[key] == value}

    def unsupported(rows: list[dict]) -> set[str]:
        return {r["id"] for r in rows if any(f["status"] == "unsupported"
                                             for f in r["attempts"][-1]["evaluation"]["failures"])}

    regressed = (ids(before, "initial_result", "PASS") - ids(after, "initial_result", "PASS")) | (
        ids(before, "final_result", "PASS") - ids(after, "final_result", "PASS"))
    checks = {
        "failures_not_worse": len(ids(after, "initial_result", "REVISE")) <= len(ids(before, "initial_result", "REVISE"))
        and len(ids(after, "final_result", "REVISE")) <= len(ids(before, "final_result", "REVISE")),
        "previously_correct_stay_correct": not regressed,
        "no_new_unsupported_answers": unsupported(after) <= unsupported(before),
    }
    return {"checks": checks, "keep": all(checks.values()), "regressed_ids": sorted(regressed),
            "initial_fail_before": sorted(ids(before, "initial_result", "REVISE")),
            "initial_fail_after": sorted(ids(after, "initial_result", "REVISE")),
            "final_fail_before": sorted(ids(before, "final_result", "REVISE")),
            "final_fail_after": sorted(ids(after, "final_result", "REVISE")),
            "unsupported_after": sorted(unsupported(after))}


def run_with(lessons: list[dict], items: list[dict]) -> list[dict]:
    SCRATCH.write_text(json.dumps(lessons, indent=2))  # use counts during validation do not touch lessons.json
    return run_items(SelfImprovingSystem(repair=True, lessons=LessonStore(SCRATCH), log=log), items)


def validate() -> None:
    print("\n=== 4.3 Validation gate ===")
    items = load_json(DATA / "validation_data.json")
    candidates = load_json(CANDIDATES)
    log("VALIDATION before any lesson")
    before = run_with([], items)
    decisions, kept = [], []
    history = [{"step": "no lessons", "summary": summarize(before)}]
    for candidate in candidates:
        log("VALIDATION with candidate", lesson=candidate["lesson_id"], kept=[x["lesson_id"] for x in kept])
        after = run_with(kept + [candidate], items)
        decision = compare(before, after)
        decisions.append({"lesson_id": candidate["lesson_id"], "pattern_key": candidate["pattern_key"],
                          "summary_before": summarize(before), "summary_after": summarize(after), **decision,
                          "results_after": after})
        history.append({"step": f"+{candidate['lesson_id']}", "summary": summarize(after), "keep": decision["keep"]})
        log("DECISION", lesson=candidate["lesson_id"], keep=decision["keep"], checks=decision["checks"])
        if decision["keep"]:
            kept.append(candidate)
            before = after
    LESSONS.write_text(json.dumps(kept, indent=2) + "\n")
    save("part4_validation.json", {"baseline_results": history[0], "history": history, "decisions": decisions,
                                   "kept": [x["lesson_id"] for x in kept],
                                   "rejected": [d["lesson_id"] for d in decisions if not d["keep"]]})
    SCRATCH.unlink(missing_ok=True)
    print(f"kept lessons -> {LESSONS.relative_to(ROOT)}: {[x['lesson_id'] for x in kept]}")


def reuse() -> None:
    print("\n=== 4.2 Lesson reuse on a later related question ===")
    store = LessonStore(LESSONS)
    before = {x["lesson_id"]: x["use_count"] for x in store.lessons}
    result = SelfImprovingSystem(repair=True, lessons=store, log=log).solve(REUSE)
    after = {x["lesson_id"]: x["use_count"] for x in store.lessons}
    loaded = [x for x in store.lessons if x["lesson_id"] in result["lessons_loaded"]]
    for lesson in loaded:
        print(f"loaded {lesson['lesson_id']} (created {lesson['created_at']} from {lesson.get('created_from')}): "
              f"{lesson['failure_pattern']} -> {lesson['correction']}  use_count {before[lesson['lesson_id']]} -> "
              f"{after[lesson['lesson_id']]}")
    print_trace(result)
    save("part4_reuse.json", {"lessons_loaded": loaded, "use_count_before": before, "use_count_after": after,
                              "result": result})


def test() -> None:
    print("\n=== 4.4 Final test: four variants on test_data.json ===")
    items = load_json(DATA / "test_data.json")
    memory = RAW / "part4_lessons_memory.json"
    shutil.copyfile(CANDIDATES, memory)  # Lesson Memory: every lesson saved in training, not validated
    variants = {
        "Baseline": dict(repair=False, lessons=None),
        "Evaluator Repair": dict(repair=True, lessons=None),
        "Lesson Memory": dict(repair=True, lessons=LessonStore(memory)),
        "Validated Improvement": dict(repair=True, lessons=LessonStore(LESSONS)),
    }
    table = {}
    for name, config in variants.items():
        log("VARIANT", name=name, lessons=[x["lesson_id"] for x in config["lessons"].lessons] if config["lessons"] else [])
        results = run_items(SelfImprovingSystem(**config, log=log), items)
        table[name] = summarize(results)
        save(f"part4_test_{name.lower().replace(' ', '_')}.json", {"summary": table[name], "results": results})
    save("part4_results.json", {"ran_at": datetime.now().isoformat(timespec="seconds"), "table": table})
    print(f"\n{'Variant':<24}{'Correct':>8}{'Incorrect':>10}{'Avg attempts':>14}{'Avg latency (ms)':>18}")
    for name, s in table.items():
        print(f"{name:<24}{s['correct']:>8}{s['incorrect']:>10}{s['avg_attempts']:>14}{s['avg_latency_ms']:>18}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phases", nargs="*", default=PHASES, choices=PHASES)
    args = parser.parse_args()
    print(f"user={getpass.getuser()} host={socket.gethostname()} time={datetime.now().isoformat(timespec='seconds')}")
    for phase in PHASES:
        if phase in args.phases:
            globals()[phase]()


if __name__ == "__main__":
    main()
