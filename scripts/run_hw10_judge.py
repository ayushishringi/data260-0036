"""HW10 Parts 3.2-3.3: run the Writer Helpfulness judge 3 times on the 20 frozen drafts.

Refuses to run unless eval_cases.json and human_labels.csv are committed, unchanged since that commit,
and every draft has a hand label 1-5 (the labels are the reference; they are never edited here).
Same inputs and settings every run (src/judge.py JUDGE_SETTINGS: qwen3:4b, temperature 0, seed 36).

Writes reports/hw10/raw/judge_runs.json (every score + reason), judge_vs_human.csv (per-case data to
recompute the statistics) and judge_validation.json (Spearman, mean absolute difference, repeatability).

Usage: make judge-hw10
"""

from __future__ import annotations

import csv
import getpass
import hashlib
import json
import socket
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.hw10_stats import judge_vs_human, repeatability  # noqa: E402
from src.judge import JUDGE_SETTINGS, METRIC_SPECS, OllamaJudge, evaluate  # noqa: E402

RAW = ROOT / "reports" / "hw10" / "raw"
FILES = ("eval_cases.json", "human_labels.csv")
RUNS = 3


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()


def frozen_commit() -> dict[str, str]:
    """The commit that froze the cases and labels; exits if they are uncommitted or changed since."""

    for name in FILES:
        if not git("ls-files", name):
            raise SystemExit(f"{name} is not committed. Commit eval_cases.json and human_labels.csv first.")
        if git("status", "--porcelain", "--", name):
            raise SystemExit(f"{name} has uncommitted changes; the labels must be judged exactly as committed.")
    sha = git("log", "-1", "--format=%H", "--", *FILES)
    return {"commit": sha, "committed_at": git("log", "-1", "--format=%cI", sha),
            **{f"{n}_sha256": hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in FILES}}


def main() -> None:
    frozen = frozen_commit()
    cases = json.loads((ROOT / "eval_cases.json").read_text())["cases"]
    with (ROOT / "human_labels.csv").open(newline="") as stream:
        labels = {r["case_id"]: r for r in csv.DictReader(stream)}
    bad = [c["case_id"] for c in cases if labels.get(c["case_id"], {}).get("helpfulness_label", "").strip()
           not in {"1", "2", "3", "4", "5"}]
    if bad:
        raise SystemExit(f"missing or invalid hand labels for {bad}; run make label-hw10 and commit")
    human = [float(labels[c["case_id"]]["helpfulness_label"]) for c in cases]
    print(f"user={getpass.getuser()} host={socket.gethostname()} time={datetime.now().isoformat(timespec='seconds')}")
    print(f"cases+labels frozen in commit {frozen['commit'][:7]} ({frozen['committed_at']})")
    print(f"judge: {JUDGE_SETTINGS}")

    judge = OllamaJudge()
    runs: list[list[dict]] = []
    for r in range(1, RUNS + 1):
        run = []
        started = time.time()
        for c in cases:
            result = evaluate("writer_helpfulness", c["question"], c["draft"] or "", c["grounding_facts"], judge=judge)
            run.append({"case_id": c["case_id"], "trace_id": c["trace_id"], **result})
            print(f"run {r} {c['case_id']} human={labels[c['case_id']]['helpfulness_label']} "
                  f"judge={result['score']} ({result['judge_ms'] / 1000:.1f}s) {result['error'] or ''}", flush=True)
        runs.append(run)
        print(f"run {r} done in {time.time() - started:.0f}s")

    scores = [[x["score"] for x in run] for run in runs]
    mean_scores = [round(statistics.mean(s), 3) if all(v is not None for v in s) else None for s in zip(*scores)]
    validation = {
        "ran_at": datetime.now().isoformat(timespec="seconds"), "frozen": frozen, "judge": JUDGE_SETTINGS,
        "metric": {"name": METRIC_SPECS["writer_helpfulness"]["name"],
                   "evaluation_steps": METRIC_SPECS["writer_helpfulness"]["steps"],
                   "rubric": METRIC_SPECS["writer_helpfulness"]["rubric"]},
        "primary": {"run": 1, **judge_vs_human(human, scores[0])},
        "per_run": [{"run": i + 1, **judge_vs_human(human, s)} for i, s in enumerate(scores)],
        "mean_of_runs": judge_vs_human(human, mean_scores),
        "repeatability": repeatability(scores),
    }
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "judge_runs.json").write_text(json.dumps({"frozen": frozen, "judge": JUDGE_SETTINGS, "runs": runs},
                                                    indent=2) + "\n")
    with (RAW / "judge_vs_human.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case_id", "category", "trace_id", "human_label", *[f"judge_run{i}" for i in range(1, RUNS + 1)],
                         "judge_mean", "abs_diff_run1", "changed_across_runs"])
        for i, c in enumerate(cases):
            s = [run[i] for run in scores]
            writer.writerow([c["case_id"], c["category"], c["trace_id"], human[i], *s, mean_scores[i],
                             None if s[0] is None else abs(human[i] - s[0]), len(set(s)) > 1])
    (RAW / "judge_validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    p, rep = validation["primary"], validation["repeatability"]
    print("\n=== Judge vs human (run 1) ===")
    print(f"Spearman rho = {p['spearman_rho']} (p = {p['spearman_p']}), mean |judge - human| = {p['mean_abs_diff']}, "
          f"exact = {p['exact_agreement']}, within 1 = {p['within_1']}")
    print("=== Repeatability (3 runs) ===")
    print(f"cases whose score changed: {rep['cases_changed']}/{rep['cases_scored_every_run']} "
          f"({rep['change_rate']}); mean |change| = {rep['mean_abs_change']}, max = {rep['max_abs_change']}")


if __name__ == "__main__":
    main()
