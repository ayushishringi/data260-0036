"""HW10 Part 1: the three dashboard pages and their cached data loaders (entry point: hw10_app.py).

Summary (traffic, cache hit rate, errors, latency), Evaluation (Part 2 scores, Part 3 judge
validation), Trace lookup (one request's spans in stage order). Everything is read from the files the
system writes; nothing here calls the agents or the judge.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import hw10_stats as stats  # noqa: E402
from src.tracing import STAGE_ORDER, span_file  # noqa: E402

RAW = ROOT / "reports" / "hw10" / "raw"
SPANS = span_file()
EVALS = RAW / "evaluations.jsonl"
NAME = "Ayushi Shringi · SID4 0036 · PREFIX s0036"
PATH_COLOR = {"hit": "#1a7f37", "miss": "#0969da", "stale": "#9a6700", "error": "#cf222e"}


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def mtime(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


# ----------------------------------------------------------------------------- cached loaders


@st.cache_data(ttl=15, show_spinner=False)
def load_jsonl(path: str, _mtime: float) -> list[dict]:
    """Parsed JSON lines; cached per file version (mtime) so reruns do not re-read unchanged files."""

    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


@st.cache_data(ttl=15, show_spinner=False)
def load_json(path: str, _mtime: float) -> dict | None:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None


@st.cache_data(ttl=15, show_spinner=False)
def load_csv(path: str, _mtime: float) -> pd.DataFrame | None:
    p = Path(path)
    return pd.read_csv(p) if p.exists() else None


@st.cache_resource(show_spinner=False)
def redis_client():
    """One Redis connection reused across reruns and sessions (expensive to create, safe to share)."""

    from src.redis_store import get_redis
    return get_redis()


def spans() -> list[dict]:
    return load_jsonl(str(SPANS), mtime(SPANS))


def evaluations() -> list[dict]:
    return load_jsonl(str(EVALS), mtime(EVALS))


def examples() -> dict:
    path = RAW / "trace_examples.json"
    return load_json(str(path), mtime(path)) or {}


def header(title: str) -> None:
    st.title(title)
    st.caption(f"{NAME} · rendered {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# ----------------------------------------------------------------------------- 1.1 summary


def summary_page() -> None:
    header("System summary")
    windows = {"Last 1 hour": timedelta(hours=1), "Last 24 hours": timedelta(days=1),
               "Last 7 days": timedelta(days=7), "All recorded": None}
    choice = st.radio("Time window", list(windows), index=2, horizontal=True)
    now = datetime.now().astimezone()
    since = now - windows[choice] if windows[choice] else None
    s = stats.summary(spans(), since.timestamp() if since else None)
    window_text = (f"{since:%Y-%m-%d %H:%M} → {now:%Y-%m-%d %H:%M} ({choice.lower()})" if since
                   else f"all recorded requests ({(s['first'] or '-')[:16]} → {(s['last'] or '-')[:16]})")
    source = f"`{rel(SPANS)}`, `request` spans (one root span per trace)"
    st.info(f"**Window:** {window_text}  \n**Source:** {source}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Requests", s["requests"])
    c1.caption(f"Distinct trace_ids with a request span. Window: {choice.lower()}.")
    c2.metric("Cache hit rate", "-" if s["hit_rate"] is None else f"{s['hit_rate']:.1%}")
    c2.caption(f"{s['hits']} hits / {s['misses']} misses ({s['requests']} requests). Source: cache_lookup result "
               "copied to the request span.")
    c3.metric("Error rate", "-" if s["error_rate"] is None else f"{s['error_rate']:.1%}")
    c3.caption(f"{s['errors']} of {s['requests']} requests ended with status=error. Window: {choice.lower()}.")
    miss, hit = s["latency_miss"], s["latency_hit"]
    c4.metric("End-to-end p50 (cache miss)", "-" if miss["p50_ms"] is None else f"{miss['p50_ms'] / 1000:.1f} s")
    c4.caption(f"p95 {(miss['p95_ms'] or 0) / 1000:.1f} s over {miss['n']} successful misses: cache lookup → "
               "agents → final answer to the client.")

    st.subheader("Cache hits and misses are separate paths")
    d1, d2 = st.columns(2)
    d1.metric("Cache-hit latency p50", "-" if hit["p50_ms"] is None else f"{hit['p50_ms']:.1f} ms",
              help="Kept separate from the miss latency (Part 4.3).")
    d1.caption(f"p95 {hit['p95_ms'] or 0:.1f} ms over {hit['n']} hits. Source: request spans with path=hit.")
    d2.metric("Cache-miss latency p50", "-" if miss["p50_ms"] is None else f"{miss['p50_ms']:,.0f} ms")
    d2.caption(f"p95 {miss['p95_ms'] or 0:,.0f} ms over {miss['n']} misses. Source: request spans with path=miss.")

    requests = [x for x in spans() if x["stage"] == "request" and (since is None or x["start_ts"] >= since.timestamp())]
    if requests:
        df = pd.DataFrame([{"time": pd.to_datetime(x["start_ts"], unit="s", utc=True).tz_convert(now.tzinfo),
                            "path": "error" if x["status"] != "ok" else x.get("path", "miss"),
                            "latency_ms": x["duration_ms"], "trace_id": x["trace_id"]} for x in requests])
        chart = alt.Chart(df).mark_circle(size=60).encode(
            x=alt.X("time:T", title="request start"),
            y=alt.Y("latency_ms:Q", scale=alt.Scale(type="log"), title="end-to-end latency (ms, log scale)"),
            color=alt.Color("path:N", scale=alt.Scale(domain=list(PATH_COLOR), range=list(PATH_COLOR.values())),
                            title="path"),
            tooltip=["trace_id", "path", "latency_ms", "time"]).properties(height=280)
        st.altair_chart(chart, width="stretch")
        st.caption(f"Each dot is one request in the window. Source: `{rel(SPANS)}`.")

    run = load_json(str(RAW / "latency_run.json"), mtime(RAW / "latency_run.json"))
    if run:
        st.subheader("Stage latency, 50 confirmed cache misses (Part 4.3)")
        table = pd.DataFrame([{"Stage": t["stage"], "p50 (ms)": f"{t['p50_ms']:,.1f}",
                               "p95 (ms)": f"{t['p95_ms']:,.1f}",
                               "% of cache-miss end-to-end": f"{(t['share_of_e2e'] or 0):.1%}"}
                              for t in run["stage_latency"]["table"]])
        st.table(table.set_index("Stage"))
        v, h = run["verification"], run["cache_hit_latency"]
        st.caption(f"Run {run['ran_at']}: {v['requests']} requests, {v['cache_lookup_miss']} cache_lookup=miss, "
                   f"{v['served_from_cache']} served from cache, {v['failed']} failed. Dominant stage: "
                   f"**{run['stage_latency']['dominant']}**. Cache-hit latency (separate metric): p50 {h['p50_ms']} ms, "
                   f"p95 {h['p95_ms']} ms over {h['n']} hits. Source: `{rel(RAW / 'latency_run.json')}`.")

    with st.expander("Live system health"):
        try:
            r = redis_client()
            entries = sum(1 for _ in r.scan_iter(match="s0036:qcache:*", count=500))
            st.write(f"Redis semantic cache entries (`s0036:qcache:*`): **{entries}** (live, via a cached "
                     "`@st.cache_resource` connection)")
        except Exception as exc:  # Redis down: the dashboard still works from files
            st.warning(f"Redis not reachable: {exc}")


# ----------------------------------------------------------------------------- 1.2 evaluation


def evaluation_page() -> None:
    header("Evaluation results")
    records = evaluations()
    e2e = load_json(str(RAW / "e2e_run.json"), mtime(RAW / "e2e_run.json")) or {}
    demo_ids = {r["trace_id"] for r in e2e.get("results", [])}
    scope = st.radio("Traces", ["Part 2 end-to-end demo", "All evaluated traces (incl. latency run)"],
                     horizontal=True)
    shown = [r for r in records if r["trace_id"] in demo_ids] if scope.startswith("Part 2") else records
    st.caption(f"Source: `{rel(EVALS)}` ({len(shown)} evaluator records). Judge: DeepEval GEval on Ollama "
               "qwen3:4b, temperature 0, seed 36, 1-5 rubric.")
    s = stats.eval_summary(shown)
    cols = st.columns(4)
    for col, key, label in zip(cols, stats.EVAL_KEYS, ("Plan quality", "Writer helpfulness", "Final helpfulness")):
        col.metric(f"{label} (mean)", s["means"][key]["mean"] if s["means"][key]["mean"] is not None else "-")
    cols[3].metric("Final − draft (mean)", s["diff_mean"] if s["diff_mean"] is not None else "-")

    st.subheader("Scores by pipeline stage and case")
    rows = []
    for r in shown:
        fv = r.get("final_vs_draft", {})
        rows.append({"trace_id": r["trace_id"], "question": r.get("question"), "outcome": r["outcome"],
                     "Plan": r.get("plan_quality", {}).get("score"),
                     "Writer": r.get("writer_helpfulness", {}).get("score"),
                     "Final": r.get("final_helpfulness", {}).get("score"), "Draft (final criterion)":
                     fv.get("draft_score"), "Final − draft": fv.get("difference"), "error": r.get("error")})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        long = pd.DataFrame([{"case": x["trace_id"][:8], "stage": stage, "score": x[stage]}
                             for x in rows for stage in ("Plan", "Writer", "Final") if x[stage] is not None])
        if not long.empty:
            st.altair_chart(alt.Chart(long).mark_bar().encode(
                x=alt.X("case:N", title="trace (first 8 chars)", axis=alt.Axis(labelAngle=0)),
                xOffset=alt.XOffset("stage:N", sort=["Plan", "Writer", "Final"]),
                y=alt.Y("score:Q", scale=alt.Scale(domain=[0, 5]), title="judge score (1-5)"),
                color=alt.Color("stage:N", sort=["Plan", "Writer", "Final"]),
                tooltip=["case", "stage", "score"]).properties(height=260), width="stretch")
        for r in shown:
            if r["outcome"] != "evaluated":
                continue
            with st.expander(f"{r['trace_id']} — {r['question']}"):
                pq, wh, fh, fv = (r["plan_quality"], r["writer_helpfulness"], r["final_helpfulness"],
                                  r["final_vs_draft"])
                st.markdown(f"**Plan quality {pq['score']}** — {pq['reason']}")
                st.markdown("\n".join(f"{n}. {step}" for n, step in enumerate(pq.get("plan") or [], 1)))
                st.markdown(f"**Writer helpfulness {wh['score']}** (trace_id `{wh['trace_id']}`) — {wh['reason']}")
                st.markdown(f"**Final answer helpfulness {fh['score']}** — {fh['reason']}")
                st.text_area("Final answer", fh["final_answer"], height=150, disabled=True,
                             key=f"final-{r['trace_id']}")
                st.markdown(f"**Final vs draft:** draft {fv['draft_score']}, final {fv['final_score']}, difference "
                            f"{fv['difference']}, identical text: {fv['draft_equals_final']}. {fv['interpretation']}")

    st.subheader("What the scores say about coordination")
    for line in stats.coordination_text(s):
        st.markdown(f"- {line}")

    st.subheader("Judge validation (Part 3)")
    val = load_json(str(RAW / "judge_validation.json"), mtime(RAW / "judge_validation.json"))
    if not val:
        st.warning("Not run yet. Label the 20 drafts (make label-hw10), commit eval_cases.json and "
                   "human_labels.csv, then run make judge-hw10.")
        return
    p, rep = val["primary"], val["repeatability"]
    st.caption(f"Cases and labels frozen in commit `{val['frozen']['commit'][:7]}` "
               f"({val['frozen']['committed_at']}); judge run {val['ran_at']}. Source: "
               f"`{rel(RAW / 'judge_validation.json')}`, `{rel(RAW / 'judge_vs_human.csv')}`.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spearman ρ (run 1)", p["spearman_rho"])
    c1.caption(f"p = {p['spearman_p']}, n = {p['n']}" if p["spearman_rho"] is not None else
               f"undefined: the judge gave every one of the {p['n']} cases the same score")
    c2.metric("Mean |judge − human|", p["mean_abs_diff"])
    c2.caption(f"exact {p['exact_agreement']:.0%}, within 1 point {p['within_1']:.0%}")
    c3.metric("Cases changed across 3 runs", f"{rep['cases_changed']}/{rep['cases_scored_every_run']}")
    c3.caption(f"pairwise change rate {rep['pairwise_change_rate']}")
    c4.metric("Mean / max |change|", f"{rep['mean_abs_change']} / {rep['max_abs_change']}")
    st.dataframe(pd.DataFrame(val["per_run"])[["run", "spearman_rho", "spearman_p", "mean_abs_diff",
                                                "exact_agreement", "within_1", "judge_mean", "human_mean"]],
                 hide_index=True, width="stretch")
    per_case = load_csv(str(RAW / "judge_vs_human.csv"), mtime(RAW / "judge_vs_human.csv"))
    if per_case is not None:
        st.dataframe(per_case, hide_index=True, width="stretch", height=35 * (len(per_case) + 1) + 3)
        # Identical (human, judge) pairs would overlap, so plot one circle per pair sized by its case count.
        pairs = (per_case.groupby(["human_label", "judge_run1"])
                 .agg(cases=("case_id", "count"), ids=("case_id", ", ".join)).reset_index())
        st.altair_chart(alt.Chart(pairs).mark_circle(opacity=0.7, color="#0969da").encode(
            x=alt.X("human_label:Q", scale=alt.Scale(domain=[0.5, 5.5]), title="human label"),
            y=alt.Y("judge_run1:Q", scale=alt.Scale(domain=[0.5, 5.5]), title="judge score (run 1)"),
            size=alt.Size("cases:Q", title="cases", scale=alt.Scale(range=[80, 900])),
            tooltip=["human_label", "judge_run1", "cases", "ids"]).properties(height=300), width="stretch")
        st.caption("Each circle is one (human, judge) pair; its size is the number of cases with that pair.")


# ----------------------------------------------------------------------------- 1.3 trace lookup


def trace_page() -> None:
    header("Trace lookup")
    ex = examples()
    if "trace_id" not in st.session_state:
        st.session_state["trace_id"] = (st.query_params.get("trace_id")
                                        or (ex.get("cache_miss") or {}).get("trace_id", ""))
    labels = {"cache_hit": "Cache hit", "cache_miss": "Cache miss (full agent path)", "failed": "Failed"}
    if ex:
        st.caption("Required examples (Part 4.2) — click to load:")
        cols = st.columns(len(ex))
        for col, (kind, item) in zip(cols, ex.items()):
            if col.button(f"{labels.get(kind, kind)}\n`{item['trace_id'][:8]}…`", width="stretch"):
                st.session_state["trace_id"] = item["trace_id"]
    trace_id = st.text_input("trace_id", key="trace_id", placeholder="paste a trace_id (= correlation_id)").strip()
    found = sorted((x for x in spans() if x.get("trace_id") == trace_id),
                   key=lambda x: (x["start_ts"], STAGE_ORDER.index(x["stage"]) if x["stage"] in STAGE_ORDER else 99))
    if not found:
        st.warning(f"No spans for trace_id `{trace_id}` in `{rel(SPANS)}`.")
        return
    path = stats.trace_path(found)
    errors = [x for x in found if x["status"] != "ok"]
    status = "error" if errors else "ok"
    kind = "error" if errors else path
    text = {"hit": "CACHE HIT — answered from Redis, agents not called", "miss": "CACHE MISS — full agent path",
            "stale": "STALE CACHE ENTRY — invalidated, full agent path", "error": "FAILED"}[kind]
    st.markdown(f"<div style='padding:10px 14px;border-radius:6px;background:{PATH_COLOR[kind]};color:white;"
                f"font-weight:600'>{text} · cache path: {path} · status: {status}</div>", unsafe_allow_html=True)
    if errors:
        # The request span only wraps the failure; report the earliest stage that actually failed.
        first = next((x for x in errors if x["stage"] != "request"), errors[0])
        st.error(f"Failing stage: **{first['stage']}** ({first.get('component')}) — {first['error']}")
    t0 = min(x["start_ts"] for x in found)
    t1 = max(x["end_ts"] for x in found)
    st.caption(f"{len(found)} spans · {(t1 - t0) * 1000:,.1f} ms from first start to last end · Source: `{rel(SPANS)}`")
    table = pd.DataFrame([{"#": n, "stage": x["stage"], "component": x.get("component"),
                           "start": x["start_time"][11:23], "end": x["end_time"][11:23],
                           "duration_ms": f"{x['duration_ms']:,.1f}", "status": x["status"],
                           "error": x.get("error") or "", "detail": detail(x)} for n, x in enumerate(found, 1)])
    # A static HTML table: every span stays visible (and printable) without scrolling inside a grid.
    st.table(table.set_index("#"))
    gantt = pd.DataFrame([{"stage": f"{n:02d} {x['stage']}", "start_ms": (x["start_ts"] - t0) * 1000,
                           "end_ms": (x["end_ts"] - t0) * 1000, "status": x["status"],
                           "duration_ms": x["duration_ms"]} for n, x in enumerate(found, 1)])
    st.altair_chart(alt.Chart(gantt).mark_bar().encode(
        x=alt.X("start_ms:Q", title="ms since the first span"), x2="end_ms:Q",
        y=alt.Y("stage:N", sort=None, title=None),
        color=alt.Color("status:N", scale=alt.Scale(domain=["ok", "error"], range=["#0969da", "#cf222e"])),
        tooltip=["stage", "duration_ms", "status"]).properties(height=max(140, 28 * len(found) + 40)),
        width="stretch")
    with st.expander("Raw spans (JSON)"):
        st.json(found)


def detail(span: dict) -> str:
    keys = ("result", "similarity", "reason", "attempt", "topic", "outcome", "scores", "path", "failed_stage")
    return ", ".join(f"{k}={span[k]}" for k in keys if span.get(k) not in (None, ""))
