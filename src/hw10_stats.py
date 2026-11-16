"""HW10 statistics shared by the scripts, METRICS.md and the dashboard.

judge_vs_human()  Spearman rank correlation (scipy, average ranks for ties) and mean absolute difference
repeatability()   how often a case's score changes across repeated judge runs, and by how much
stage_latency()   per-trace stage durations of cache-miss traces -> p50 / p95 / share of end-to-end
summary()         request count, cache hit rate, error rate and latency for the dashboard summary page
"""

from __future__ import annotations

import itertools
import statistics
from collections import defaultdict
from typing import Any

import numpy as np

QUEUE_STAGES = ("queue_inbox", "queue_tasks", "queue_drafts", "queue_final")
REQUIRED_STAGES = ("cache_lookup", "planner", "writer", "reviewer", "queue_wait_total", "evaluation")
STAGE_LABEL = {"cache_lookup": "Cache lookup", "planner": "Planner", "writer": "Writer", "reviewer": "Reviewer",
               "queue_wait_total": "Queue wait (total)", "evaluation": "Evaluation", "other": "Other (client, store)"}


def pct(values: list[float], q: float) -> float | None:
    return round(float(np.percentile(values, q)), 2) if values else None


# ----------------------------------------------------------------------------- Part 3


def judge_vs_human(human: list[float], judge: list[float]) -> dict[str, Any]:
    from scipy.stats import spearmanr

    pairs = [(h, j) for h, j in zip(human, judge) if h is not None and j is not None]
    hs, js = [p[0] for p in pairs], [p[1] for p in pairs]
    rho, p_value = spearmanr(hs, js) if len(pairs) > 2 else (float("nan"), float("nan"))
    diffs = [abs(h - j) for h, j in pairs]
    return {"n": len(pairs), "spearman_rho": None if np.isnan(rho) else round(float(rho), 4),
            "spearman_p": None if np.isnan(p_value) else round(float(p_value), 4),
            "mean_abs_diff": round(statistics.mean(diffs), 4) if diffs else None,
            "exact_agreement": round(sum(d == 0 for d in diffs) / len(diffs), 4) if diffs else None,
            "within_1": round(sum(d <= 1 for d in diffs) / len(diffs), 4) if diffs else None,
            "judge_mean": round(statistics.mean(js), 3) if js else None,
            "human_mean": round(statistics.mean(hs), 3) if hs else None}


def repeatability(runs: list[list[float | None]]) -> dict[str, Any]:
    """runs[r][c] = score of case c in run r (same inputs, same settings)."""

    cases = list(zip(*runs))
    complete = [c for c in cases if all(s is not None for s in c)]
    changed = [c for c in complete if len(set(c)) > 1]
    pair_diffs = [abs(a - b) for c in complete for a, b in itertools.combinations(c, 2)]
    ranges = [max(c) - min(c) for c in complete]
    return {"runs": len(runs), "cases": len(cases), "cases_scored_every_run": len(complete),
            "cases_changed": len(changed),
            "change_rate": round(len(changed) / len(complete), 4) if complete else None,
            "pairwise_changes": sum(d > 0 for d in pair_diffs), "pairwise_comparisons": len(pair_diffs),
            "pairwise_change_rate": round(sum(d > 0 for d in pair_diffs) / len(pair_diffs), 4) if pair_diffs else None,
            "mean_abs_change": round(statistics.mean(pair_diffs), 4) if pair_diffs else None,
            "mean_abs_change_when_changed": round(statistics.mean([d for d in pair_diffs if d > 0]), 4)
            if any(pair_diffs) else 0.0,
            "max_abs_change": round(max(ranges), 4) if ranges else None,
            "failed_scores": sum(s is None for run in runs for s in run)}


# ----------------------------------------------------------------------------- Part 4


def by_trace(spans: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in spans:
        if s.get("trace_id"):
            out[s["trace_id"]].append(s)
    return out


def trace_path(spans: list[dict[str, Any]]) -> str:
    """hit / miss / stale from the cache_lookup span (miss if a trace went straight to Kafka)."""

    lookup = next((s for s in spans if s["stage"] == "cache_lookup"), None)
    return lookup.get("result", "miss") if lookup else "miss"


def trace_breakdown(spans: list[dict[str, Any]]) -> dict[str, float] | None:
    """Stage durations (ms) of one completed cache-miss trace; None if a required span is missing."""

    stages: dict[str, float] = defaultdict(float)
    for s in spans:
        stages[s["stage"]] += s["duration_ms"]
    needed = ("cache_lookup", "planner", "writer", "reviewer", "evaluation", "request")
    if any(n not in stages for n in needed) or any(s["status"] != "ok" for s in spans):
        return None
    start = min(s["start_ts"] for s in spans)
    end = max(s["end_ts"] for s in spans)
    out = {k: round(stages[k], 2) for k in ("cache_lookup", "planner", "writer", "reviewer", "evaluation")}
    out.update({q: round(stages.get(q, 0.0), 2) for q in QUEUE_STAGES})
    out["queue_wait_total"] = round(sum(stages.get(q, 0.0) for q in QUEUE_STAGES), 2)
    out["end_to_end"] = round((end - start) * 1000, 2)
    out["user_facing"] = round(next(s["duration_ms"] for s in spans if s["stage"] == "request"), 2)
    out["other"] = round(out["end_to_end"] - sum(out[k] for k in REQUIRED_STAGES), 2)
    return out


def stage_latency(spans: list[dict[str, Any]], trace_ids: list[str] | None = None) -> dict[str, Any]:
    """p50/p95 per stage and each stage's share of cache-miss end-to-end latency.

    End-to-end = first span start (cache lookup) -> last span end (evaluation). Share = sum of the stage's
    time over all traces / sum of end-to-end time over all traces.
    """

    grouped = by_trace(spans)
    ids = trace_ids if trace_ids is not None else list(grouped)
    rows = []
    for tid in ids:
        t = grouped.get(tid, [])
        if trace_path(t) != "miss":
            continue
        b = trace_breakdown(t)
        if b is not None:
            rows.append({"trace_id": tid, **b})
    total_e2e = sum(r["end_to_end"] for r in rows)
    table = []
    for key in (*REQUIRED_STAGES, "other"):
        values = [r[key] for r in rows]
        table.append({"stage": STAGE_LABEL[key], "key": key, "p50_ms": pct(values, 50), "p95_ms": pct(values, 95),
                      "mean_ms": round(statistics.mean(values), 2) if values else None,
                      "share_of_e2e": round(sum(values) / total_e2e, 4) if total_e2e else None})
    queues = [{"stage": q, "p50_ms": pct([r[q] for r in rows], 50), "p95_ms": pct([r[q] for r in rows], 95)}
              for q in QUEUE_STAGES]
    e2e = [r["end_to_end"] for r in rows]
    user = [r["user_facing"] for r in rows]
    dominant = max((t for t in table if t["key"] in REQUIRED_STAGES), key=lambda t: t["share_of_e2e"] or 0,
                   default=None)
    return {"traces": len(rows), "table": table, "queues": queues,
            "end_to_end": {"p50_ms": pct(e2e, 50), "p95_ms": pct(e2e, 95)},
            "user_facing": {"p50_ms": pct(user, 50), "p95_ms": pct(user, 95)},
            "dominant": dominant and dominant["stage"], "rows": rows}


def summary(spans: list[dict[str, Any]], since_ts: float | None = None, until_ts: float | None = None) -> dict[str, Any]:
    """Dashboard summary over the `request` spans whose start falls inside the window."""

    requests = [s for s in spans if s["stage"] == "request"
                and (since_ts is None or s["start_ts"] >= since_ts) and (until_ts is None or s["start_ts"] <= until_ts)]
    hits = [s for s in requests if s.get("path") == "hit" and s["status"] == "ok"]
    misses = [s for s in requests if s.get("path") != "hit"]
    errors = [s for s in requests if s["status"] != "ok"]
    ok_misses = [s for s in misses if s["status"] == "ok"]
    lat = lambda xs: {"p50_ms": pct([s["duration_ms"] for s in xs], 50),  # noqa: E731
                      "p95_ms": pct([s["duration_ms"] for s in xs], 95), "n": len(xs)}
    return {"requests": len(requests), "hits": len(hits), "misses": len(misses), "errors": len(errors),
            "hit_rate": round(len(hits) / len(requests), 4) if requests else None,
            "error_rate": round(len(errors) / len(requests), 4) if requests else None,
            "latency_all": lat([s for s in requests if s["status"] == "ok"]),
            "latency_hit": lat(hits), "latency_miss": lat(ok_misses),
            "first": min((s["start_time"] for s in requests), default=None),
            "last": max((s["start_time"] for s in requests), default=None)}


# ----------------------------------------------------------------------------- Part 2


EVAL_KEYS = ("plan_quality", "writer_helpfulness", "final_helpfulness")


def eval_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean score per stage, draft-vs-final comparison and failures over evaluator records."""

    done = [r for r in records if r.get("outcome") == "evaluated"]
    means = {}
    for key in EVAL_KEYS:
        scores = [r[key]["score"] for r in done if r[key]["score"] is not None]
        means[key] = {"mean": round(statistics.mean(scores), 2) if scores else None, "n": len(scores),
                      "min": min(scores, default=None), "max": max(scores, default=None)}
    fv = [r["final_vs_draft"] for r in done]
    diffs = [f["difference"] for f in fv if f["difference"] is not None]
    approved_low = [r for r in done if r["final_helpfulness"].get("review_status") == "approved"
                    and r["final_helpfulness"]["score"] is not None and r["final_helpfulness"]["score"] <= 2]
    return {"records": len(records), "evaluated": len(done),
            "not_evaluated": sum(r.get("outcome") == "not_evaluated" for r in records),
            "incomplete": sum(r.get("outcome") == "incomplete" for r in records),
            "judge_errors": sum(r.get("status") == "error" for r in done), "means": means,
            "draft_equals_final": sum(f["draft_equals_final"] for f in fv),
            "diff_mean": round(statistics.mean(diffs), 3) if diffs else None,
            "diff_nonzero": sum(d != 0 for d in diffs), "improved": sum(d > 0 for d in diffs),
            "regressed": sum(d < 0 for d in diffs), "approved_but_low": len(approved_low)}


def coordination_text(s: dict[str, Any]) -> list[str]:
    """What the scores say about Planner -> Writer -> Reviewer coordination (no forced positive reading)."""

    if not s["evaluated"]:
        return ["No evaluated traces yet."]
    m = {k: s["means"][k]["mean"] for k in EVAL_KEYS}
    out = [f"Over {s['evaluated']} evaluated traces the judge's mean scores are Plan {m['plan_quality']}, "
           f"Writer draft {m['writer_helpfulness']} and Final answer {m['final_helpfulness']} (1-5)."]
    if m["plan_quality"] is not None and m["writer_helpfulness"] is not None:
        if m["plan_quality"] < m["writer_helpfulness"]:
            out.append("Plans score lower than the drafts written from them: the Writer leans on the advisory facts "
                       "and its own knowledge more than on the plan, so a weak plan rarely sinks the answer, but the "
                       "Planner is the weakest link in the hand-off.")
        else:
            out.append("Plans score at least as high as the drafts: the Planner hands over usable steps, and the "
                       "loss happens in the Writer, which does not fully turn a good plan into a good answer.")
    if s["draft_equals_final"] == s["evaluated"]:
        out.append(f"The final answer is identical to the draft in all {s['evaluated']} traces: the Reviewer only "
                   "applies rule checks (length, on-topic) and approves or flags the draft without rewriting it, so "
                   "the final answer did not improve on the draft. Any non-zero final-minus-draft difference "
                   f"({s['diff_nonzero']} of {s['evaluated']}, mean {s['diff_mean']}) is judge variance on identical text.")
    else:
        out.append(f"The final answer differs from the draft in {s['evaluated'] - s['draft_equals_final']} traces; "
                   f"{s['improved']} improved and {s['regressed']} regressed (mean change {s['diff_mean']}).")
    if s["approved_but_low"]:
        out.append(f"The Reviewer approved {s['approved_but_low']} answer(s) the judge scored 2 or lower, so its checks "
                   "do not catch factual or relevance problems; an LLM review step with the advisory facts would.")
    return out
