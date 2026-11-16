"""Build the HW10 report (reports/hw10/Shringi_HW10.pdf and .docx) from the saved HW10 evidence.

Layout follows the HW9 report: Arial/Helvetica, 14 pt part headings, 12 pt subsections, 11 pt body,
grey-header tables, italic centered figure captions. Numbers are read from reports/hw10/raw/ and the
span file; code figures are rendered from the current source lines; console figures from saved logs
and from git/sha256 output. Dashboard screenshots come from reports/hw10/screenshots/.

Usage: make report-hw10
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image
from pygments import highlight
from pygments.formatters import ImageFormatter
from pygments.lexers import JsonLexer, PythonLexer, TextLexer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import tracing  # noqa: E402

HW = ROOT / "reports" / "hw10"
RAW = HW / "raw"
SHOTS = HW / "screenshots"
FIGS = HW / "report_figures"
PDF_OUT = HW / "Shringi_HW10.pdf"
DOCX_OUT = HW / "Shringi_HW10.docx"
FONT = "/System/Library/Fonts/Menlo.ttc"


# ----------------------------------------------------------------------------- evidence


def load(name: str) -> dict:
    return json.loads((RAW / name).read_text())


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


E2E, EX, LAT, VAL = load("e2e_run.json"), load("trace_examples.json"), load("latency_run.json"), load(
    "judge_validation.json")
CASES = {c["case_id"]: c for c in json.loads((ROOT / "eval_cases.json").read_text())["cases"]}
with (RAW / "judge_vs_human.csv").open() as _s:
    PER_CASE = list(csv.DictReader(_s))
SPANS = tracing.load_spans()
EVALS = [e for e in E2E["evaluations"] if e["outcome"] == "evaluated"]
FAILED_EVAL = next(e for e in E2E["evaluations"] if e["outcome"] != "evaluated")


def hw10_commit() -> str:
    """Latest commit that contains the HW10 code, or a reminder when it is not committed yet."""

    sha = git("log", "-1", "--format=%h", "--", "src/tracing.py", "src/evaluator.py", "dashboard/hw10_app.py")
    if not sha:
        return "HW10 code not committed yet (commit, tag hw10, then rerun make report-hw10)"
    return f"{sha} ({git('log', '-1', '--format=%s', sha)})"


def short(tid: str) -> str:
    return tid[:8]


# ----------------------------------------------------------------------------- figure rendering


def render(code: str, lexer, out: Path, start: int | None = None) -> Path:
    fmt = ImageFormatter(style="github-dark", font_name=FONT, font_size=15, line_numbers=start is not None,
                         line_number_start=start or 1, line_number_bg="#0d1117", line_number_fg="#6e7681",
                         line_pad=3, image_pad=14)
    out.write_bytes(highlight(code, lexer, fmt))
    return out


def stack(parts: list[Path], out: Path) -> Path:
    """Stack several rendered blocks vertically with a thin white gap (like the HW9 code figures)."""

    images = [Image.open(p).convert("RGB") for p in parts]
    width = max(i.width for i in images)
    canvas = Image.new("RGB", (width, sum(i.height for i in images) + 8 * (len(images) - 1)), "white")
    y = 0
    for img in images:
        canvas.paste(img, (0, y))
        y += img.height + 8
    canvas.save(out)
    return out


def split_shot(path: Path, y: int) -> tuple[Path, Path]:
    """Split a tall dashboard screenshot at pixel row y; the lower half keeps the page's sidebar column."""

    FIGS.mkdir(parents=True, exist_ok=True)
    im = Image.open(path)
    top, bottom = FIGS / f"{path.stem}_top.png", FIGS / f"{path.stem}_bottom.png"
    im.crop((0, 0, im.width, y)).save(top)
    im.crop((0, y, im.width, im.height)).save(bottom)
    return top, bottom


def code_fig(name: str, ranges: list[tuple[str, int, int]]) -> Path:
    parts = []
    for n, (file, a, b) in enumerate(ranges):
        lines = (ROOT / file).read_text().splitlines()[a - 1:b]
        parts.append(render("\n".join(lines), PythonLexer(), FIGS / f"_{name}_{n}.png", a))
    return stack(parts, FIGS / f"{name}.png") if len(parts) > 1 else parts[0].rename(FIGS / f"{name}.png")


def wrap(text: str, width: int = 118) -> str:
    out = []
    for line in text.splitlines():
        while len(line) > width:
            out.append(line[:width])
            line = "  " + line[width:]
        out.append(line)
    return "\n".join(out)


def console_fig(name: str, blocks: list[tuple[str, str]], lexer=None) -> Path:
    """blocks: (command, output); rendered as a terminal transcript of saved output."""

    text = "\n".join(f"$ {cmd}\n{wrap(output)}" for cmd, output in blocks)
    return render(text, lexer or TextLexer(), FIGS / f"{name}.png")


def run(cmd: str) -> str:
    return subprocess.run(cmd, cwd=ROOT, shell=True, capture_output=True, text=True).stdout.rstrip()


def build_figures() -> dict[str, Path]:
    FIGS.mkdir(parents=True, exist_ok=True)
    f: dict[str, Path] = {}
    f["loaders"] = code_fig("loaders", [("dashboard/hw10_views.py", 44, 78)])
    f["join"] = code_fig("join", [("src/evaluator.py", 89, 113)])
    f["score"] = code_fig("score", [("src/evaluator.py", 153, 188)])
    f["judge"] = code_fig("judge", [("src/judge.py", 38, 60), ("src/judge.py", 125, 138)])
    f["write_span"] = code_fig("write_span", [("src/tracing.py", 46, 64), ("src/agent_pipeline.py", 216, 224)])
    f["cache_span"] = code_fig("cache_span", [("src/semantic_cache.py", 160, 173)])
    f["agent_span"] = code_fig("agent_span", [("src/agent_pipeline.py", 165, 203)])

    e2e_log = (RAW / "e2e_console.log").read_text().splitlines()
    keep = [ln for ln in e2e_log if ln.startswith(("#", "   evaluation span", "   error", "   evaluator saw",
                                                   "===", "6ab", "c92", "722", "942", "cache_", "failed "))]
    f["e2e_log"] = console_fig("e2e_log", [("make e2e-hw10   # saved in reports/hw10/raw/e2e_console.log",
                                            "\n".join(keep))])
    sha = run("shasum -a 256 eval_cases.json human_labels.csv")
    f["frozen"] = console_fig("frozen", [
        ("git log --format='%h %cI %s' -- eval_cases.json human_labels.csv",
         git("log", "--format=%h %cI %s", "--", "eval_cases.json", "human_labels.csv")),
        ("git status --porcelain -- eval_cases.json human_labels.csv   # empty = unchanged since the commit",
         git("status", "--porcelain", "--", "eval_cases.json", "human_labels.csv") or "(no output)"),
        ("shasum -a 256 eval_cases.json human_labels.csv", sha),
        ("grep -E 'commit|committed_at|sha256|ran_at' reports/hw10/raw/judge_validation.json",
         run("grep -E '\"(commit|committed_at|eval_cases.json_sha256|human_labels.csv_sha256|ran_at)\"' "
             "reports/hw10/raw/judge_validation.json")),
        ("head -3 reports/hw10/raw/judge_console.log | tail -2",
         run("head -3 reports/hw10/raw/judge_console.log | tail -2"))])
    judge_log = (RAW / "judge_console.log").read_text().splitlines()
    run3 = [ln for ln in judge_log if ln.startswith("run 3 E")]
    tail = [ln for ln in judge_log[judge_log.index(run3[-1]) + 1:] if "ConstantInputWarning" not in ln
            and "spearmanr(" not in ln]
    f["judge_log"] = console_fig("judge_log", [("make judge-hw10   # last of 3 runs, from judge_console.log",
                                                "\n".join(run3 + tail))])
    miss = tracing.trace(SPANS, EX["cache_miss"]["trace_id"])
    pick = [s for s in miss if s["stage"] in ("cache_lookup", "queue_tasks", "writer", "evaluation")]
    slim = [{k: v for k, v in s.items() if k not in ("start_ts", "end_ts")} for s in pick]
    f["span_json"] = render("$ grep 6ab316ab reports/hw10/traces/spans.jsonl   # 4 of the 11 spans\n"
                            + "\n".join(json.dumps(s, default=str) for s in slim).replace(", \"", ",\n  \""),
                            JsonLexer(), FIGS / "span_json.png")
    lat_log = (RAW / "latency_console.log").read_text().splitlines()
    head = [ln for ln in lat_log if ln.startswith(("115 of", "miss  1/", "miss  2/", "miss 49/", "miss 50/",
                                                   "hit  1/", "hit 10/"))]
    table_start = next(i for i, ln in enumerate(lat_log) if ln.startswith("verified:"))
    f["latency_log"] = console_fig("latency_log", [("make latency-hw10   # excerpt of latency_console.log",
                                                    "\n".join(head + ["..."] + lat_log[table_start:]))])
    ver = run("grep -E '^\\[(PASS|FAIL)\\]|checks passed' reports/hw10/verify_console.log")
    f["verify"] = console_fig("verify", [("make verify-hw10", ver)])
    return f


# ----------------------------------------------------------------------------- content model
# ("h1", text) ("h2", text) ("p", text with **bold**) ("bullets", [..]) ("numbers", [..])
# ("table", header, rows, bold_rows) ("fig", path, caption, width_in) ("break",)


def content(f: dict[str, Path]) -> list[tuple]:
    st = LAT["stage_latency"]
    tab = {t["stage"]: t for t in st["table"]}
    hit = LAT["cache_hit_latency"]
    v = LAT["verification"]
    val, rep = VAL, VAL["repeatability"]
    p = val["primary"]
    labels = [int(float(r["human_label"])) for r in PER_CASE]
    dist = ", ".join(f"{n} × {k}" for k, n in sorted({k: labels.count(k) for k in set(labels)}.items()))
    cats: dict[str, list[float]] = {}
    for r in PER_CASE:
        cats.setdefault(r["category"], []).append(float(r["human_label"]))
    rows_by_kind = {k: tracing.trace(SPANS, it["trace_id"]) for k, it in EX.items()}

    def span_total(s: list[dict]) -> float:
        return (max(x["end_ts"] for x in s) - min(x["start_ts"] for x in s)) * 1000

    ev = {short(e["trace_id"]): e for e in EVALS}
    c: list[tuple] = []
    a = c.append

    # Section 0
    a(("h1", "Section 0: Configuration"))
    a(("table", ["Setting", "Value"], [
        ["Name", "Ayushi Shringi"],
        ["GitHub repository", "https://github.com/ayushishringi/data260-0036/tree/hw5"],
        ["SID4", "0036"], ["PORT_BASE", "8036 (dashboard on 8038)"], ["PREFIX", "s0036"], ["SEED", "36"],
        ["DOMAIN_ID", "4 (36 mod 8): open-source package vulnerability tracking"],
        ["Kafka topics", "s0036_inbox, s0036_tasks (2 partitions), s0036_drafts, s0036_final, s0036_dead_letter"],
        ["Redis", "Redis Stack (container s0036-redis), semantic cache s0036:qcache:*, threshold 0.85"],
        ["Hardware", "MacBook Pro, Apple M5 Pro, 24 GB"],
        ["Agents and judge", "Ollama qwen3:4b (num_ctx 16384), no paid APIs"],
        ["Judge framework", "DeepEval 4.3.4 GEval, temperature 0, seed 36, 1-5 rubric"],
        ["Dashboard", "Streamlit 1.67.0 (make dashboard-hw10)"],
        ["Branch", "hw5"], ["Tag", "hw10"],
        ["Eval cases + labels frozen", f"{val['frozen']['commit'][:7]} ({val['frozen']['committed_at']})"],
        ["HW10 code commit", hw10_commit()],
    ], []))
    a(("p", "**Pipeline.** A question first goes to the HW9 semantic cache. On a miss it goes to the HW8 agents "
            "over Kafka: s0036_inbox → Planner → s0036_tasks → Writer → s0036_drafts → Reviewer → s0036_final. "
            "The answer is returned to the client and stored in the cache. The new HW10 evaluator reads "
            "s0036_tasks, s0036_drafts, s0036_final and s0036_dead_letter and scores each finished request. "
            "Every step writes a JSON span to reports/hw10/traces/spans.jsonl under one trace_id, which is the "
            "Kafka correlation_id."))
    a(("p", "All numbers in this report come from files in reports/hw10/ (raw/, traces/spans.jsonl, "
            "METRICS.md). make verify-hw10 recomputes them from those files and passes 21 of 21 checks "
            "(Figure 18)."))
    a(("break",))

    # Part 1
    a(("h1", "Part 1: Operations Dashboard"))
    a(("p", "dashboard/hw10_app.py is a three-page Streamlit app (Summary, Evaluation, Trace lookup). The sidebar "
            "shows my name, SID4 and PREFIX on every page. All pages read the saved evidence files, so the "
            "screenshots match the numbers in this report."))
    a(("h2", "1.1 Summary page"))
    a(("fig", SHOTS / "01_summary.png", "Figure 1 – Summary page: request count, cache hit rate (hits and misses "
                                         "separately), error rate and end-to-end latency, each with its window "
                                         "and source", 6.5))
    a(("p", "A selector sets the time window (last hour, 24 hours, 7 days, all). The blue box and the caption "
            "under each metric name the window and the data source. Source: reports/hw10/traces/spans.jsonl, "
            "one root request span per trace."))
    a(("table", ["Metric", "Value (last 7 days)", "How it is computed"], [
        ["Request count", "70", "Distinct trace_ids with a request span: 5 from a superseded first end-to-end "
                                "run, 5 from the final end-to-end run, 50 latency-run misses, 10 cache hits"],
        ["Cache hit rate", "17.1% (12 hits / 58 misses)", "cache_lookup result copied to the request span; hits "
                                                          "and misses also shown as two separate latencies"],
        ["Error rate", "2.9% (2 of 70)", "Requests that ended with status=error. Both are the injected Writer "
                                         "fault, once in each end-to-end run"],
        ["End-to-end latency", "p50 41.0 s, p95 59.6 s", "Request span over 56 successful misses: cache lookup "
                                                         "→ agents → answer returned to the client"],
        ["Cache-hit latency", "p50 5.2 ms, p95 48.2 ms", "Request span over the 12 hits"],
    ], []))
    a(("p", "The request span ends when the client gets the answer. The evaluator scores the answer afterwards, "
            "so its time is not in this number. Part 4.3 adds it and reports the full cache-miss end-to-end "
            "time. The page also shows every request's latency on a log scale, colored by path, and the 4.3 "
            "stage table."))
    a(("p", "**Caching.** @st.cache_data(ttl=15) wraps the loaders for spans.jsonl, evaluations.jsonl, the JSON "
            "results and the CSV. The file's modification time is part of the cache key, so a new span shows up "
            "within 15 s and an unchanged file is not parsed again on every rerun. @st.cache_resource keeps one "
            "Redis connection for the live-health panel, shared across reruns and sessions (Figure 2)."))
    a(("fig", f["loaders"], "Figure 2 – Cached loaders: @st.cache_data keyed by file mtime and "
                            "@st.cache_resource for the Redis client (dashboard/hw10_views.py)", 6.5))
    a(("h2", "1.2 Evaluation page"))
    top, bottom = split_shot(SHOTS / "02_evaluation.png", 1400)
    a(("p", "The top half (Figure 3a) shows the Part 2 evaluator records (reports/hw10/raw/evaluations.jsonl). It "
            "has the mean score per criterion, a table and grouped bar chart of Plan, Writer and Final scores per "
            "trace, an expander per trace with each criterion's reason, the plan and the final answer, and a "
            "coordination summary generated from the scores. A switch also shows all 55 evaluated traces, "
            "including the latency run."))
    a(("fig", top, "Figure 3a – Evaluation page, top: Part 2 scores by stage and case and the coordination "
                   "interpretation", 6.5))
    a(("p", "The bottom half (Figure 3b) shows Part 3:"))
    a(("bullets", ["Spearman rho, shown as undefined with the reason.",
                   "Mean absolute difference and the three-run repeatability.",
                   "The per-run table and the per-case table.",
                   "A judge-vs-human plot where circle size counts the cases on each point."]))
    a(("fig", bottom, "Figure 3b – Evaluation page, bottom: Part 3 Spearman, mean absolute difference, "
                      "repeatability and per-case judge vs human labels", 6.5))
    a(("h2", "1.3 Trace lookup page"))
    a(("p", "The user pastes a trace_id (the same value as the correlation_id), opens a link with ?trace_id=, or "
            "clicks one of the three example buttons. The page shows:"))
    a(("bullets", ["A colored banner: green for a cache hit, blue for a full agent path, red for a failure, "
                   "with the failing stage and its error.",
                   "Every span in start order, with stage, component, start, end, duration, status, error and "
                   "details.",
                   "A timeline chart of the spans, and the raw span JSON."]))
    a(("p", "A hit and a miss are easy to tell apart. A hit has only the request and cache_lookup spans (Figure "
            "4). A miss shows the whole chain of queues and agents plus the evaluation (Figure 15). The failed "
            "example is Figure 16."))
    a(("fig", SHOTS / "03_trace_hit.png", f"Figure 4 – Trace lookup, cache-hit path "
                                          f"({EX['cache_hit']['trace_id']}): 2 spans, "
                                          f"{span_total(rows_by_kind['cache_hit']):.1f} ms, no agent spans", 6.5))
    a(("break",))

    # Part 2
    a(("h1", "Part 2: End-to-End Evaluator"))
    a(("h2", "2.1 How the evaluator works"))
    a(("p", "evaluator.py runs as its own Kafka consumer group on four topics:"))
    a(("bullets", ["s0036_tasks: the Planner's plan.",
                   "s0036_drafts: the Writer's draft and the advisory facts it used.",
                   "s0036_final: the Reviewer's final answer.",
                   "s0036_dead_letter: failed messages."]))
    a(("p", "Each message is added to a join keyed by correlation_id (Figure 5):"))
    a(("bullets", ["When plan, draft and final are all present, the request is scored.",
                   "A dead-letter message closes the join as not_evaluated and records the upstream error.",
                   "A join that waits longer than 600 s closes as incomplete.",
                   "Messages without a correlation_id are logged and skipped."]))
    a(("p", "**Bounded.** Each judge call has a 240 s timeout, and each trace has a total budget of 900 s. If "
            "Ollama is down, the criteria are recorded with status error instead of blocking the consumer. "
            "Each trace produces exactly one record, appended to reports/hw10/raw/evaluations.jsonl, and one "
            "evaluation span."))
    a(("p", "**Judge.** The judge is DeepEval GEval with a custom DeepEvalBaseLLM (OllamaJudge, Figure 7). It "
            "calls the local qwen3:4b through the same ModelClient as the agents, with temperature 0, seed 36 "
            "and Ollama structured output in the JSON schema DeepEval asks for. The evaluation steps are fixed "
            "in the code, so GEval does not generate new steps on each run. The rubric has five bands, one per "
            "score from 1 to 5. GEval returns 0–1, which is mapped back to 1 + 4 × score. Thinking is on: with "
            "it off, a call took about 1 s but rated a reasonable three-step plan 1/5 in a spot check. With "
            "thinking, a call takes 20–100 s."))
    a(("table", ["Criterion", "Judged text", "Context given to the judge", "Saved fields"], [
        ["Plan Quality", "Planner's plan steps", "question", "score, reason, plan"],
        ["Writer Helpfulness", "Writer's draft", "question + advisory record the Writer used (or a "
                                                 "\"no record\" note)", "score, reason, trace_id, facts"],
        ["Final Helpfulness", "Reviewer's final answer", "question", "score, reason, final answer"],
        ["Final vs Draft", "draft, scored with the Final criterion", "question",
         "both scores, difference, draft==final, interpretation"],
    ], []))
    a(("fig", f["join"], "Figure 5 – Evaluator join on correlation_id, dead-letter handling and join timeout "
                         "(src/evaluator.py)", 6.5))
    a(("fig", f["score"], "Figure 6 – score(): four bounded judge calls and the saved fields "
                          "(src/evaluator.py)", 6.5))
    a(("fig", f["judge"], "Figure 7 – OllamaJudge (DeepEvalBaseLLM on local qwen3:4b) and the GEval metric "
                          "with fixed steps and a 1-5 rubric (src/judge.py)", 6.5))
    a(("h2", "2.2 Results"))
    a(("p", f"make e2e-hw10 ({E2E['ran_at']}) asked three new questions, repeated question 1 as a cache hit, "
            "and sent one question with an injected Writer fault. The script waited for each evaluation before "
            "the next question."))
    rows = []
    for e in EVALS:
        fv = e["final_vs_draft"]
        rows.append([short(e["trace_id"]), e["question"], f"{e['plan_quality']['score']:.0f}",
                     f"{e['writer_helpfulness']['score']:.0f}", f"{e['final_helpfulness']['score']:.0f}",
                     f"{fv['draft_score']:.0f}", f"{fv['difference']:+.0f}"])
    rows.append([short(FAILED_EVAL["trace_id"]), FAILED_EVAL["question"], "–", "–", "–", "–",
                 "not evaluated (writer → dead letter)"])
    a(("table", ["trace_id", "Question", "Plan", "Writer", "Final", "Draft", "Final − draft"], rows, []))
    a(("fig", f["e2e_log"], "Figure 8 – End-to-end run: each request with its trace_id, evaluation span and "
                            "scores; the failed request reaches the evaluator as not_evaluated", 6.5))
    j, g, s = ev["6ab316ab"], ev["c924d3d9"], ev["7226904b"]
    a(("p", "**Plan Quality (score and reason).**"))
    a(("bullets", [f"6ab316ab, score {j['plan_quality']['score']:.0f}: \"{j['plan_quality']['reason']}\"",
                   f"c924d3d9, score {g['plan_quality']['score']:.0f}: \"{g['plan_quality']['reason']}\"",
                   f"7226904b, score {s['plan_quality']['score']:.0f}: \"{s['plan_quality']['reason']}\""]))
    a(("p", "**Writer Helpfulness (score and trace_id).** All three drafts scored 5. For example, trace "
            f"{j['writer_helpfulness']['trace_id']}: \"{j['writer_helpfulness']['reason']}\""))
    a(("p", "**Final Helpfulness (score and final answer).** All three finals scored 5. Final answer of trace "
            f"c924d3d9 (excerpt): \"{g['final_helpfulness']['final_answer'][:420]}…\""))
    a(("h2", "2.3 Final vs draft: no improvement"))
    a(("p", "The final-minus-draft difference is 0 for all three questions, and this is not judge noise. The final "
            "text is byte-identical to the draft each time (draft_equals_final = true). The HW8 Reviewer is "
            "rule-based: it checks length, topic and that the cited facts match, then approves or flags the "
            "draft. It never rewrites, so the final stage adds a quality gate but no quality. The evaluator "
            "reports this as \"No improvement: the Reviewer approved the draft without rewriting it\". It does "
            "not report a positive difference."))
    a(("h2", "2.4 What the scores say about coordination"))
    a(("p", "The plans contain facts that the record contradicts, and the Writer fixes them:"))
    a(("bullets", [
        "**jackson-databind (6ab316ab).** The plan says \"Find CVE-2021-44228, fixed version 2.12.0, Critical\". "
        "That CVE is Log4Shell, not this bug. The s0036_rel record says CVE-2020-36518, fixed in 2.13.2.1, "
        "severity high. The Writer answered from the record and even wrote \"(not CVE-2021-44228)\".",
        "**golang.org/x/net (c924d3d9).** The plan says to upgrade to 0.16.0, but the record says fixed in "
        "0.17.0. The Writer wrote \"Do not upgrade to 0.16.0\".",
        "**SBOM (7226904b).** The plan lists three valid reasons (finding vulnerable dependencies, compliance, "
        "faster patching). The judge still gave it 1, saying it \"describes steps to generate\" an SBOM, which "
        "the plan does not do."]))
    a(("p", "So the correct answers come from the Writer's grounding in the advisory database, not from the "
            "plan. The Planner is the weakest agent: it adds about 32 s per answer (Part 4.3) and, without the "
            "record, invents version facts. The plan scores (4, 5, 1) are nearly the reverse of the plans' "
            "actual correctness, which is a first sign that the judge does not check facts (Part 3). Possible "
            "fixes:"))
    a(("bullets", ["Give the Planner the advisory record.",
                   "Or limit the plan to steps with no version facts.",
                   "Have the Reviewer check the plan against the record."]))
    a(("break",))

    # Part 3
    a(("h1", "Part 3: Judge Validation"))
    a(("h2", "3.1 Evaluation cases and hand labels"))
    a(("p", "eval_cases.json holds 20 Writer drafts produced by the HW8 pipeline (grounded Writer, qwen3:4b). "
            "Each case has its trace_id, question, plan, draft and the advisory facts the Writer saw. The "
            "questions were chosen to cover easy and hard cases:"))
    a(("table", ["Category", "Count", "What it tests", "Example"], [
        ["Grounded", "8", "Package is in s0036_rel; the draft should match the record",
         "Which version of minimist fixes the prototype pollution bug?"],
        ["Not in database", "5", "No record; the draft must not invent versions or CVEs",
         "Which spring-core version fixes CVE-2022-22965?"],
        ["General", "4", "Practice question with no single fact", "Should I pin transitive dependencies?"],
        ["Vague", "3", "Under-specified question", "Is it safe?"],
    ], []))
    a(("p", f"human_labels.csv has columns case_id, trace_id, helpfulness_label and notes. I labeled every draft "
            f"by hand, using the same 1–5 rubric the judge uses (1 = wrong or does not answer; 3 = answers with "
            f"errors or omissions; 5 = accurate, direct and complete). No model produced or suggested a label. "
            f"Distribution: {dist}; mean {p['human_mean']}."))
    a(("p", f"**Frozen before the judge.** Both files were committed in {val['frozen']['commit'][:7]} at "
            f"{val['frozen']['committed_at']}. The judge run started 19 s later, at 12:25:34, and finished at "
            f"{val['ran_at']}. run_hw10_judge.py refuses to start unless both files are tracked and unmodified, "
            "and it records the commit and their sha256. Figure 9 shows that the working files, the commit and "
            "the recorded hashes match."))
    a(("fig", f["frozen"], "Figure 9 – eval_cases.json and human_labels.csv: commit, unchanged working files, "
                           "sha256 = the hashes recorded by the judge run, and the judge start time", 6.5))
    a(("h2", "3.2 Agreement with the human labels"))
    a(("table", ["Run", "Spearman rho", "Mean |judge − human|", "Exact", "Within 1", "Judge mean", "Human mean"],
       [[str(r["run"]), "undefined", str(r["mean_abs_diff"]), f"{r['exact_agreement']:.0%}",
         f"{r['within_1']:.0%}", str(r["judge_mean"]), str(r["human_mean"])] for r in val["per_run"]], []))
    a(("p", "The judge gave **every one of the 20 drafts a 5, in all three runs**. Spearman's rho needs variance "
            "in both rankings. With a constant judge score it is undefined (SciPy returns NaN), so it is "
            "reported as undefined, not as 0. Mean absolute difference is 1.3 points. The 35% exact agreement "
            "is exactly the 7 drafts I rated 5. The judge's error is largest where the drafts are worst:"))
    a(("table", ["Category", "Cases", "Human mean", "Judge mean", "Gap"],
       [[k, str(len(vals)), f"{sum(vals) / len(vals):.2f}", "5.00", f"{5 - sum(vals) / len(vals):.2f}"]
        for k, vals in cats.items()], []))
    a(("p", "Three drafts that I rated low and the judge rated 5:"))
    a(("bullets", [
        "**E12 (human 1).** Asked which spring-core version fixes CVE-2022-22965 (Spring4Shell), the draft "
        "says 5.3.20, gives a made-up release date, and says 5.3.0–5.3.19 are affected. The fix shipped in "
        "5.3.18 / 5.2.20. Judge: \"accurately identifies the fixed spring-core version as 5.3.20 … without "
        "factual errors\".",
        "**E13 (human 2).** The draft calls the xz backdoor \"CVE-2023-3231\" with versions < 5.2.5. The real "
        "CVE is CVE-2024-3094, affecting xz 5.6.0 and 5.6.1. Judge: \"accurately identifies the real "
        "CVE-2023-3231 … without invention\".",
        "**E10 (human 3).** The event-stream draft gives a version and a CVE (CVE-2017-12000) that do not match "
        "the 2018 incident. Judge: \"accurately confirms … using well-established public knowledge\"."]))
    a(("p", "None of these packages has a record in s0036_rel, so the judge had to check facts on its own. A 4B "
            "model does not know them and accepts any confident, well-formatted answer."))
    a(("h2", "3.3 Repeatability"))
    a(("p", f"The judge scored the 20 frozen drafts three times with identical settings. "
            f"{rep['cases_changed']}/{rep['cases_scored_every_run']} cases changed score (change rate "
            f"{rep['change_rate']:.0%}); {rep['pairwise_changes']}/{rep['pairwise_comparisons']} run pairs "
            f"differ; mean absolute change {rep['mean_abs_change']}, max {rep['max_abs_change']}. This is "
            "expected with temperature 0, a fixed seed and fixed evaluation steps, since Ollama then returns the "
            "same output. The judge is perfectly repeatable, but repeatable is not the same as correct: it "
            "gives the same wrong score every time."))
    a(("fig", f["judge_log"], "Figure 10 – Judge run 3 of 3 and the summary: Spearman undefined, mean |diff| "
                              "1.3, 0/20 cases changed across runs", 6.5))
    a(("h2", "3.4 Should this judge be trusted?"))
    a(("p", "**No, not as it is.** It cannot be used for absolute scores, since everything is 5. It cannot rank "
            "drafts, because its scores never vary. It cannot gate answers either, because it passed the E12 "
            "and E13 drafts, which contain wrong security facts. The Writer and Final scores of 5 in Part 2 "
            "therefore carry no information. The plan scores are not better (Part 2.4). The causes:"))
    a(("bullets", ["The judge is the same small model as the agents, so it shares their knowledge gaps.",
                   "For questions without a database record, it is asked to check facts it does not have.",
                   "Fluent, confident text reads as accurate to it."]))
    a(("p", "What would make it usable:"))
    a(("numbers", [
        "Give the judge the reference answer for every case (reference_facts.json covers 23 packages), or "
        "check the fields deterministically like the HW9 Evaluator Agent, and let the LLM judge only the "
        "wording.",
        "Use a stronger judge model than the model being judged.",
        "Add anchor examples of 1–3 drafts to the rubric, and make \"unverifiable claim\" an explicit "
        "deduction.",
        "Re-validate on new hand-labeled cases. These 20 labels have now been seen, so tuning the judge on "
        "them would overfit."]))
    a(("break",))

    # Part 4
    a(("h1", "Part 4: Distributed Tracing and Latency"))
    a(("h2", "4.1 One trace_id across the whole pipeline"))
    a(("p", "The client creates a UUID trace_id for each request and passes it to the cache handler "
            "(CachedQA.ask). The same value is the Kafka correlation_id of the inbox message:"))
    a(("bullets", ["Each agent copies trace_id from its input message to its output message.",
                   "The dead-letter message carries it too.",
                   "The evaluator joins on it.",
                   "There is no second identifier. make verify-hw10 checks that plan, draft and final messages "
                   "all have correlation_id == trace_id."]))
    a(("p", "Every component appends one JSON line per span to reports/hw10/traces/spans.jsonl under a file "
            "lock (Figure 11). Each span has trace_id, span_id, stage, component, start_time, end_time, "
            "duration_ms, status and error, plus stage details such as similarity, topic, partition, offset, "
            "attempt and scores."))
    a(("table", ["Stage", "Written by", "Measures"], [
        ["request", "client", "the whole request until the answer is returned (root span)"],
        ["cache_lookup", "cache handler", "embed + KNN search + threshold/version check; result hit/miss/stale"],
        ["queue_inbox / tasks / drafts / final", "the consuming agent",
         "Kafka message create time → consumer receive time"],
        ["planner / writer / reviewer", "agent", "processing of one attempt (ok or error)"],
        ["dead_letter", "agent", "move to s0036_dead_letter after the last failed attempt"],
        ["cache_store", "cache handler", "storing the approved answer"],
        ["evaluation", "evaluator", "the four judge calls (or not_evaluated with the upstream error)"],
    ], []))
    a(("fig", f["write_span"], "Figure 11 – write_span() (src/tracing.py) and the queue-wait span from the "
                               "Kafka message timestamp (src/agent_pipeline.py)", 6.5))
    a(("fig", f["cache_span"], "Figure 12 – cache_lookup span with result=hit or miss (src/semantic_cache.py)",
       6.5))
    a(("fig", f["agent_span"], "Figure 13 – Agent spans: injected fault, trace_id copied to the next message, "
                               "error span per attempt and the dead_letter span (src/agent_pipeline.py)", 6.5))
    a(("fig", f["span_json"], "Figure 14 – Spans of the cache-miss trace as saved in spans.jsonl (4 of 11 "
                              "shown)", 6.5))
    a(("h2", "4.2 Three trace examples"))
    trows = []
    for kind, label in (("cache_hit", "Cache hit"), ("cache_miss", "Cache miss"), ("failed", "Failed")):
        sp = rows_by_kind[kind]
        errs = [x for x in sp if x["status"] != "ok" and x["stage"] != "request"]
        trows.append([label, EX[kind]["trace_id"], str(len(sp)), f"{span_total(sp):,.1f}",
                      f"error at {errs[0]['stage']}" if errs else "ok"])
    a(("table", ["Example", "trace_id", "Spans", "First start → last end (ms)", "Status"], trows, []))
    a(("bullets", [
        "**Cache hit** (Figure 4): request → cache_lookup (hit, similarity 1.0). No agent, queue or "
        "evaluation span.",
        "**Cache miss** (Figure 15): request → cache_lookup (miss, empty cache) → queue_inbox → planner "
        "(50.1 s) → queue_tasks → writer (7.0 s) → queue_drafts → reviewer → queue_final → cache_store → "
        "evaluation (240.5 s). The answer reached the client after 59.0 s.",
        "**Failed** (Figure 16): the question carried inject_fault=writer. The planner succeeded. The writer "
        "failed 3 attempts with \"injected fault … simulated Ollama timeout\". The message went to "
        "s0036_dead_letter, the client got PipelineFailed, and the evaluator wrote an evaluation span with "
        "outcome not_evaluated and the upstream error."]))
    a(("fig", SHOTS / "04_trace_miss.png", f"Figure 15 – Trace lookup, cache-miss path "
                                           f"({EX['cache_miss']['trace_id']})", 6.5))
    a(("fig", SHOTS / "05_trace_failed.png", f"Figure 16 – Trace lookup, failed request "
                                             f"({EX['failed']['trace_id']}): failing stage writer, dead letter, "
                                             f"not evaluated", 6.5))
    a(("h2", "4.3 Stage latency over 50 cache misses"))
    a(("p", f"**Method.** make latency-hw10 built 115 candidate questions (5 templates × 23 packages, shuffled "
            f"with seed 36). It kept only those whose nearest cached query was below the 0.85 threshold and "
            f"sent the first 50 one at a time, with store_on_miss=False so that no request could be answered "
            f"from a cached earlier one. It waited for each evaluation before sending the next request, so "
            f"requests never queued behind each other. The run took {LAT['duration_s'] / 60:.0f} min. "
            f"Verification: {v['requests']} requests, {v['cache_lookup_miss']} cache_lookup=miss, "
            f"{v['served_from_cache']} served from cache, {v['failed']} failed. Then 10 repeated questions "
            f"measured the cache-hit path separately."))
    order = ["Cache lookup", "Planner", "Writer", "Reviewer", "Queue wait (total)", "Evaluation"]
    lrows = [[k, f"{tab[k]['p50_ms']:,.1f}", f"{tab[k]['p95_ms']:,.1f}", f"{tab[k]['share_of_e2e']:.1%}"]
             for k in order]
    lrows.append(["End-to-end (cache miss)", f"{st['end_to_end']['p50_ms']:,.1f}",
                  f"{st['end_to_end']['p95_ms']:,.1f}", "100%"])
    a(("table", ["Stage", "p50 (ms)", "p95 (ms)", "% of cache-miss end-to-end"], lrows, [5]))
    a(("p", f"End-to-end runs from the start of the cache lookup to the end of the evaluation. % of end-to-end "
            f"is the stage's total time over all 50 traces divided by the total end-to-end time. The remaining "
            f"time (client work, cache store and span overlap) is −0.0%: the evaluation span starts a few ms "
            f"before cache_store ends, because both run right after the final message. "
            f"Queue waits: inbox p50 {st['queues'][0]['p50_ms']} ms, tasks {st['queues'][1]['p50_ms']} ms, "
            f"drafts {st['queues'][2]['p50_ms']} ms, final {st['queues'][3]['p50_ms']} ms. User-facing latency "
            f"(request span) is p50 {st['user_facing']['p50_ms'] / 1000:.1f} s, p95 "
            f"{st['user_facing']['p95_ms'] / 1000:.1f} s."))
    a(("p", f"**Cache-hit latency (separate metric).** {hit['n']} hits: p50 {hit['p50_ms']} ms, p95 "
            f"{hit['p95_ms']} ms, about 9,000 times faster than a miss for the user."))
    a(("fig", f["latency_log"], "Figure 17 – Latency run: 50 confirmed misses, the verification line and the "
                                "stage table, then the 10 cache hits", 6.5))
    a(("p", "**Dominant stage: Evaluation**, 78.9% of the cache-miss end-to-end time (p50 152 s). The Planner "
            "is next at 17.1%. For the user, who does not wait for the evaluation, the Planner dominates: 80.7% "
            "of user-facing time (p50 32.1 s of 40.8 s). The Writer takes 19.1%, while the cache lookup, the "
            "Reviewer and all four Kafka queues together take well under 1%."))
    a(("p", "**What to change, in order of effect:**"))
    a(("numbers", [
        "**Evaluate a sample, not every request.** One evaluation (about 152 s) takes 3.7 times as long as "
        "one answer (about 41 s). Under steady load, an evaluator that scores every trace falls behind without "
        "limit. Scoring 10–20% of traces, or only the Writer criterion, keeps up. Given Part 3, the judge "
        "should also be replaced by a reference check that takes milliseconds.",
        "**Shrink or remove the Planner.** Its 32 s is mostly qwen3:4b thinking tokens, and Part 2 showed "
        "that its version facts are often wrong and ignored by the Writer. Turning thinking off for the "
        "Planner, or merging its outline into the Writer prompt, would cut user-facing p50 from about 41 s "
        "toward the Writer's 7–8 s.",
        "**Raise the safe cache-hit rate.** A hit takes 4.6 ms. The HW9 field-aware cache key would let more "
        "paraphrases hit without false hits.",
        "**Leave Kafka alone.** The queue waits add up to about 35 ms (p50), so partitions and consumer "
        "settings are not the bottleneck."]))
    a(("fig", f["verify"], "Figure 18 – make verify-hw10: span format, one identifier, Part 2 fields, the "
                           "three traces, the 50-miss table recomputed from spans, frozen labels, judge "
                           "statistics recomputed from the CSV, dashboard pages, unit tests and ruff", 6.5))
    a(("break",))

    # AI use
    a(("h1", "AI Use"))
    for para in (HW / "AI_USE.md").read_text().split("\n\n")[1:]:
        a(("p", re.sub(r"^(\d\. [^.]+\.)", r"**\1**", para.strip())))
    return c


# ----------------------------------------------------------------------------- PDF (reportlab)


def md_xml(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(text))
    return re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', text)


def col_widths(header: list[str], rows: list[list], width: float) -> list[float]:
    """Every column at least as wide as its longest word; the rest of the width goes to long-text columns."""

    cols = list(zip(header, *rows))
    floor = [max(len(w) for x in col for w in str(x).split() or [""]) * 6.8 + 12 for col in cols]
    need = [max(len(str(x)) for x in col) * 5.4 + 12 for col in cols]
    if sum(floor) >= width:
        return [width * f / sum(floor) for f in floor]
    extra = [max(n - f, 0) for n, f in zip(need, floor)]
    spare = width - sum(floor)
    if sum(extra) <= spare:
        grow = extra
        leftover = spare - sum(extra)
        grow = [g + leftover * (n / sum(need)) for g, n in zip(grow, need)]
    else:
        grow = [spare * e / sum(extra) for e in extra]
    return [f + g for f, g in zip(floor, grow)]


def build_pdf(blocks: list[tuple]) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (Image as RLImage, KeepTogether, ListFlowable, ListItem, PageBreak,
                                    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=14, leading=18, spaceBefore=6, spaceAfter=8,
                        keepWithNext=1)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12, leading=15, spaceBefore=8, spaceAfter=5,
                        keepWithNext=1)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=11, leading=14.5, spaceAfter=7)
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=10, leading=12.5)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold")
    cap = ParagraphStyle("cap", fontName="Helvetica-Oblique", fontSize=11, leading=14, alignment=TA_CENTER,
                         spaceBefore=4, spaceAfter=12)
    width = letter[0] - 2 * inch
    story: list = []
    for b in blocks:
        kind = b[0]
        if kind == "h1":
            story.append(Paragraph(md_xml(b[1]), h1))
        elif kind == "h2":
            story.append(Paragraph(md_xml(b[1]), h2))
        elif kind == "p":
            story.append(Paragraph(md_xml(b[1]), body))
        elif kind in ("bullets", "numbers"):
            items = [ListItem(Paragraph(md_xml(t), body), leftIndent=14) for t in b[1]]
            story.append(ListFlowable(items, bulletType="bullet" if kind == "bullets" else "1",
                                      bulletFontName="Helvetica", bulletFontSize=11, leftIndent=16,
                                      start="•" if kind == "bullets" else 1))
        elif kind == "table":
            header, rows, bold_rows = b[1], b[2], b[3]
            data = [[Paragraph(md_xml(h), head) for h in header]]
            for i, r in enumerate(rows, 1):
                style = head if i in bold_rows else cell
                data.append([Paragraph(md_xml(str(x)), style) for x in r])
            t = Table(data, colWidths=col_widths(header, rows, width), repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#444444")),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFEFEF")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
            story += [t, Spacer(1, 10)]
        elif kind == "fig":
            path, caption, w_in = b[1], b[2], b[3]
            with Image.open(path) as im:
                w, h = im.size
            draw_w = min(w_in * inch, width)
            draw_h = draw_w * h / w
            max_h = 8.3 * inch
            if draw_h > max_h:
                draw_w, draw_h = draw_w * max_h / draw_h, max_h
            story.append(KeepTogether([RLImage(str(path), width=draw_w, height=draw_h),
                                       Paragraph(md_xml(caption), cap)]))
        elif kind == "break":
            story.append(PageBreak())
    doc = SimpleDocTemplate(str(PDF_OUT), pagesize=letter, leftMargin=inch, rightMargin=inch, topMargin=inch,
                            bottomMargin=inch, title="DATA 260 HW10 – Ayushi Shringi", author="Ayushi Shringi")
    doc.build(story)


# ----------------------------------------------------------------------------- DOCX (python-docx)


def build_docx(blocks: list[tuple]) -> None:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    for section in doc.sections:
        section.left_margin = section.right_margin = section.top_margin = section.bottom_margin = Inches(1)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Arial", Pt(11)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")

    def runs(par, text: str, size: int = 11, bold: bool = False, italic: bool = False) -> None:
        text = text.replace("`", "")
        for n, piece in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
            if piece:
                r = par.add_run(piece)
                r.font.name, r.font.size = "Arial", Pt(size)
                r.bold, r.italic = bold or n % 2 == 1, italic
                r.font.color.rgb = RGBColor(0, 0, 0)

    def shade(cell_) -> None:
        tc_pr = cell_._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), "EFEFEF")
        tc_pr.append(shd)

    for b in blocks:
        kind = b[0]
        if kind in ("h1", "h2"):
            par = doc.add_paragraph()
            par.paragraph_format.space_before, par.paragraph_format.space_after = Pt(8), Pt(6)
            par.paragraph_format.keep_with_next = True
            runs(par, b[1], 14 if kind == "h1" else 12, bold=True)
        elif kind == "p":
            runs(doc.add_paragraph(), b[1])
        elif kind in ("bullets", "numbers"):
            for t in b[1]:
                runs(doc.add_paragraph(style="List Bullet" if kind == "bullets" else "List Number"), t)
        elif kind == "table":
            header, rows, bold_rows = b[1], b[2], b[3]
            t = doc.add_table(rows=1, cols=len(header))
            t.style, t.alignment = "Table Grid", WD_TABLE_ALIGNMENT.CENTER
            for k, h in enumerate(header):
                t.rows[0].cells[k].text = ""
                runs(t.rows[0].cells[k].paragraphs[0], h, 10, bold=True)
                shade(t.rows[0].cells[k])
            for i, r in enumerate(rows, 1):
                cells = t.add_row().cells
                for k, x in enumerate(r):
                    runs(cells[k].paragraphs[0], str(x), 10, bold=i in bold_rows)
            doc.add_paragraph()
        elif kind == "fig":
            path, caption, w_in = b[1], b[2], b[3]
            with Image.open(path) as im:
                w, h = im.size
            draw_w = min(w_in, 6.5)
            if draw_w * h / w > 8.3:
                draw_w = 8.3 * w / h
            par = doc.add_paragraph()
            par.alignment = WD_ALIGN_PARAGRAPH.CENTER
            par.paragraph_format.keep_with_next = True
            par.add_run().add_picture(str(path), width=Inches(draw_w))
            cap = doc.add_paragraph()
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            runs(cap, caption, 11, italic=True)
        elif kind == "break":
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    doc.core_properties.author, doc.core_properties.title = "Ayushi Shringi", "DATA 260 HW10"
    doc.save(DOCX_OUT)


def main() -> None:
    (HW / "verify_console.log").write_text(subprocess.run(
        [sys.executable, "scripts/verify_hw10.py"], cwd=ROOT, capture_output=True, text=True).stdout)
    blocks = content(build_figures())
    build_pdf(blocks)
    build_docx(blocks)
    from pypdf import PdfReader
    pages = len(PdfReader(str(PDF_OUT)).pages)
    digest = hashlib.sha256(PDF_OUT.read_bytes()).hexdigest()[:12]
    print(f"wrote {PDF_OUT.relative_to(ROOT)} ({pages} pages, sha256 {digest}…) and {DOCX_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
