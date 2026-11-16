"""Smoke test for DATA-260 HW10; writes reports/hw10/verification.json.

Checks the saved evidence and the code, not wording: span format, one identifier per request
(trace_id == correlation_id in every span and Kafka message), the three trace examples, the Part 2
evaluation records, the 50-miss latency run, the frozen eval cases / hand labels and (once run) the
judge statistics recomputed from the per-case CSV, the dashboard pages rendering without errors
(Streamlit AppTest), the unit tests and ruff. No model calls.

Usage: make verify-hw10
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import tracing  # noqa: E402
from src.hw10_stats import judge_vs_human, repeatability, stage_latency, trace_path  # noqa: E402

RAW = ROOT / "reports" / "hw10" / "raw"
OUTPUT = ROOT / "reports" / "hw10" / "verification.json"
SPAN_FIELDS = {"trace_id", "stage", "start_time", "end_time", "status", "error", "duration_ms"}
checks: list[dict] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"check": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")


def load(name: str) -> dict | None:
    path = RAW / name
    return json.loads(path.read_text()) if path.exists() else None


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def main() -> None:
    spans = tracing.load_spans()
    check("spans: every span has trace_id, stage, start/end time, status, error", bool(spans) and all(
        SPAN_FIELDS <= set(s) for s in spans), f"{len(spans)} spans in {tracing.span_file().relative_to(ROOT)}")
    stages = {s["stage"] for s in spans}
    check("spans cover cache lookup, inbox, tasks, drafts, final and the evaluator",
          {"cache_lookup", "queue_inbox", "planner", "queue_tasks", "writer", "queue_drafts", "reviewer",
           "queue_final", "evaluation"} <= stages, sorted(stages))

    e2e = load("e2e_run.json")
    ex = load("trace_examples.json")
    if e2e and ex:
        evals = [e for e in e2e["evaluations"] if e["outcome"] == "evaluated"]
        ids_match = all(m.get("correlation_id") == e["trace_id"] and m.get("trace_id", e["trace_id"]) == e["trace_id"]
                        for e in e2e["evaluations"] for m in e["messages"].values())
        check("one identifier: plan/draft/final messages carry correlation_id == trace_id", ids_match,
              f"{len(e2e['evaluations'])} evaluator records")
        full = [e for e in evals if all(e[k]["score"] is not None for k in
                                        ("plan_quality", "writer_helpfulness", "final_helpfulness"))
                and e["final_vs_draft"]["difference"] is not None]
        check("Part 2: >=1 end-to-end question scored on all four criteria (1-5)", len(full) >= 1 and all(
            1 <= e[k]["score"] <= 5 for e in full for k in ("plan_quality", "writer_helpfulness", "final_helpfulness")),
            f"{len(full)} fully scored")
        check("Part 2: saved fields (plan reason, writer trace_id, final answer, both scores + interpretation)",
              all(e["plan_quality"]["reason"] and e["writer_helpfulness"]["trace_id"] == e["trace_id"]
                  and e["final_helpfulness"]["final_answer"] and e["final_vs_draft"]["interpretation"] for e in full))
        hit = tracing.trace(spans, ex["cache_hit"]["trace_id"])
        miss = tracing.trace(spans, ex["cache_miss"]["trace_id"])
        failed = tracing.trace(spans, ex["failed"]["trace_id"])
        check("4.2 cache-hit trace: cache_lookup=hit, no agent spans",
              trace_path(hit) == "hit" and not {"planner", "writer"} & {s["stage"] for s in hit},
              [s["stage"] for s in hit])
        check("4.2 cache-miss trace: miss -> planner -> writer -> reviewer -> evaluation, all ok",
              trace_path(miss) == "miss" and {"planner", "writer", "reviewer", "evaluation"} <= {s["stage"] for s in miss}
              and all(s["status"] == "ok" for s in miss), [s["stage"] for s in miss])
        errs = [s for s in failed if s["status"] == "error" and s["stage"] == "writer"]
        check("4.2 failed trace: failing stage and error recorded", bool(errs)
              and any(s["stage"] == "dead_letter" for s in failed), errs[0]["error"] if errs else None)
    else:
        check("Part 2 / 4.2 evidence saved (make e2e-hw10)", False)

    lat = load("latency_run.json")
    if lat:
        v = lat["verification"]
        check("4.3: 50 requests, all cache_lookup=miss, none served from cache", v["requests"] == 50
              and v["cache_lookup_miss"] == 50 and v["served_from_cache"] == 0, v)
        recomputed = stage_latency(spans, [r["trace_id"] for r in lat["requests"]])
        check("4.3: stage table recomputes from spans (p50/p95/share for 6 stages)",
              [t["p50_ms"] for t in recomputed["table"]] == [t["p50_ms"] for t in lat["stage_latency"]["table"]]
              and len([t for t in recomputed["table"] if t["key"] != "other"]) == 6,
              {t["stage"]: t["p50_ms"] for t in recomputed["table"]})
        check("4.3: cache-hit latency kept as a separate metric", lat["cache_hit_latency"]["n"] > 0,
              lat["cache_hit_latency"])
    else:
        check("4.3 latency run saved (make latency-hw10)", False)

    cases_path, labels_path = ROOT / "eval_cases.json", ROOT / "human_labels.csv"
    if cases_path.exists() and labels_path.exists():
        cases = json.loads(cases_path.read_text())["cases"]
        with labels_path.open(newline="") as stream:
            labels = list(csv.DictReader(stream))
        check("3.1: eval_cases.json has 20 Writer drafts with trace ids",
              len(cases) == 20 and all(c["draft"] and c["trace_id"] for c in cases), len(cases))
        labeled = [r for r in labels if r["helpfulness_label"].strip() in {"1", "2", "3", "4", "5"}]
        check("3.1: human_labels.csv has a 1-5 label for every draft", len(labeled) == 20 == len(labels),
              f"{len(labeled)}/{len(labels)} labeled")
        committed = bool(git("ls-files", "eval_cases.json", "human_labels.csv")) and not git(
            "status", "--porcelain", "--", "eval_cases.json", "human_labels.csv")
        check("3.1: cases and labels committed and unchanged", committed,
              git("log", "-1", "--format=%h %cI", "--", "eval_cases.json", "human_labels.csv") or "not committed")
    else:
        check("3.1: eval_cases.json and human_labels.csv exist (make cases-hw10)", False)

    val = load("judge_validation.json")
    if val:
        with (RAW / "judge_vs_human.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        num = lambda x: None if x in ("", "None") else float(x)  # noqa: E731
        human = [float(r["human_label"]) for r in rows]
        runs = [[num(r[f"judge_run{i}"]) for r in rows] for i in (1, 2, 3)]
        again, rep = judge_vs_human(human, runs[0]), repeatability(runs)
        check("3.2: Spearman and mean |diff| recompute from judge_vs_human.csv",
              again["spearman_rho"] == val["primary"]["spearman_rho"]
              and again["mean_abs_diff"] == val["primary"]["mean_abs_diff"], again)
        check("3.3: three runs, repeatability recomputes", rep == val["repeatability"], rep)
        committed_at = datetime.fromisoformat(val["frozen"]["committed_at"]).astimezone().replace(tzinfo=None)
        check("3.1: labels committed before the judge ran", committed_at < datetime.fromisoformat(val["ran_at"]),
              (val["frozen"]["committed_at"], val["ran_at"]))
    else:
        check("3.2-3.3: judge validation run (make judge-hw10)", False, "pending: needs hand labels + commit")

    try:
        from streamlit.testing.v1 import AppTest
        errors = {}
        for page in ("summary", "evaluation", "trace"):
            at = AppTest.from_file(str(ROOT / "dashboard" / "hw10_app.py"), default_timeout=60)
            at.switch_page(f"hw10_pages/{page}.py")
            at.run()
            errors[page] = [e.value for e in at.exception]
        check("dashboard: Summary, Evaluation and Trace lookup pages render without exceptions",
              not any(errors.values()), errors)
    except Exception as exc:  # AppTest itself unavailable or failed
        check("dashboard: pages render (Streamlit AppTest)", False, f"{type(exc).__name__}: {exc}")
    source = (ROOT / "dashboard" / "hw10_views.py").read_text()
    check("dashboard uses @st.cache_data and @st.cache_resource", "@st.cache_data" in source
          and "@st.cache_resource" in source)

    tests = subprocess.run([sys.executable, "-m", "unittest", "tests.test_hw10"], cwd=ROOT, capture_output=True,
                           text=True)
    check("unit tests (tests/test_hw10.py)", tests.returncode == 0, tests.stderr.strip().splitlines()[-1])
    files = ["src/tracing.py", "src/judge.py", "src/evaluator.py", "src/hw10_pipeline.py", "src/hw10_stats.py",
             "evaluator.py", "dashboard/hw10_app.py", "dashboard/hw10_views.py", "tests/test_hw10.py", *map(str, (ROOT / "scripts").glob("*hw10*"))]
    lint = subprocess.run([sys.executable, "-m", "ruff", "check", *files], cwd=ROOT, capture_output=True, text=True)
    check("ruff on HW10 files", lint.returncode == 0, lint.stdout.strip().splitlines()[-1] if lint.stdout else "")

    passed = sum(c["ok"] for c in checks)
    OUTPUT.write_text(json.dumps({"verified_at": datetime.now().isoformat(timespec="seconds"), "passed": passed,
                                  "total": len(checks), "checks": checks}, indent=2, default=str) + "\n")
    print(f"\n{passed}/{len(checks)} checks passed -> {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
