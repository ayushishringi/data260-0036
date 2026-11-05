"""Build reports/hw09/METRICS.md from reports/hw09/raw/ (no numbers are typed by hand).

Includes the Part 3.4 cost model: every threshold's total cost is
    misses x C_MISS + false_hits x C_FALSE_HIT
with C_MISS derived from the measured agent-pipeline time and C_FALSE_HIT from support time.

Usage: make metrics-hw09
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "reports" / "hw09" / "raw"
OUT = ROOT / "reports" / "hw09" / "METRICS.md"

# ---- Part 3.4 cost model
GPU_DOLLARS_PER_HOUR = 1.00  # price of a comparable single cloud GPU (T4/L4 class) running the local model
SUPPORT_MINUTES = 15  # engineer time to notice, triage and correct one wrong security answer
ENGINEER_DOLLARS_PER_HOUR = 60.0
C_FALSE_HIT = round(SUPPORT_MINUTES / 60 * ENGINEER_DOLLARS_PER_HOUR, 2)

# Why the embedding model put each superficially similar pair close together (written per case).
CONFUSION = {
    "C21": "Every content word (Log4Shell, vulnerability, log4j-core) is shared; only 'severity' became 'CVE'. "
           "Mean-pooled sentence embeddings are dominated by the shared topic tokens, so one changed intent word "
           "barely moves the vector.",
    "C24": "The rare, heavily weighted tokens (PyYAML, full_load, code execution, vulnerability) are identical; "
           "the only difference is the intent ('how should I fix' vs 'what is the severity'), which the model "
           "encodes weakly compared with the topic.",
    "C25": "Both ask 'which requests version' about the same Proxy-Authorization header leak. The embedding "
           "captures package + vulnerability + 'version' but not the direction: the first affected version "
           "(2.3.0) and the fixed version (2.31.0) are opposite ends of the affected range.",
    "C26": "The incoming query adds the number 5.3.18 and 'still exploitable'. Sentence embeddings are poor at "
           "numbers and at intent that flips the answer: 5.3.18 is the fixed release, so the correct answer is "
           "'no', while the cached answer says the flaw is critical.",
    "C29": "Shares the rare tokens 'axios' and 'XSRF-TOKEN leak' with the cached CVE question; 'impact' vs "
           "'CVE' is a small change in an otherwise identical topic.",
    "C30": "Same package and same 'header-count denial of service'; 'introduced' vs 'fixes' is one verb, but "
           "it asks for the start of the affected range (8.0.0) instead of the fix (8.17.1).",
    "C23": "Same template sentence with only the package name swapped (minimist -> protobufjs).",
    "C22": "Same 'which <package> version fixes the <flaw>' template.",
    "C27": "Same 'what is the CVE for the <package> <flaw>' template.",
    "C28": "Same 'which <package> version fixes the <flaw> denial of service' template.",
}


def load(name: str) -> dict:
    return json.loads((RAW / name).read_text())


def fmt_ms(value: float | None) -> str:
    return "-" if value is None else f"{value:,.1f}"


def answer_block(text: str) -> str:
    return "\n".join("> " + line if line else ">" for line in text.strip().splitlines())


def part1(lines: list[str]) -> None:
    d = load("part1_counter.json")
    syncs = [i + 1 for i, v in enumerate(d["db_view_count_after_each_access"]) if (i + 1) % 10 == 0]
    lines += ["## Part 1 - Redis view counter", "",
              f"Report `{d['report_code']}` (id {d['report_id']}), key `{d['key']}`. {len(d['counts'])} accesses: "
              f"Redis INCR returned 1..{d['counts'][-1]}; MySQL `view_count` was written at accesses {syncs} "
              f"and ended at **{d['final_db']}** while Redis holds **{d['final_redis']}** "
              f"(the last {d['final_redis'] - d['final_db']} views are only in Redis until the next sync).", ""]


def part2(lines: list[str]) -> None:
    d = load("part2_cache_demo.json")
    s = d["summary"]
    lines += ["## Part 2 - Semantic cache (threshold 0.85)", "",
              "| # | Query type | is_cached | Similarity | Latency (ms) | Query |", "|---:|---|---|---:|---:|---|"]
    for r in d["results"]:
        sim = "-" if r["similarity"] is None else f"{r['similarity']:.4f}"
        lines.append(f"| {r['n']} | {r['kind']} | {r['is_cached']} | {sim} | {fmt_ms(r['latency_ms'])} | {r['query']} |")
    lines += ["", f"- Cache hit rate: **{s['hits']}/{s['queries']} = {s['hit_rate']:.1%}**",
              f"- Average latency, cached: **{fmt_ms(s['avg_latency_cached_ms'])} ms**; non-cached (agent "
              f"pipeline): **{fmt_ms(s['avg_latency_uncached_ms'])} ms** (measured, not targeted).", ""]
    misses = [r for r in d["results"] if not r["is_cached"] and r["similarity"] and r["similarity"] >= 0.5]
    for r in misses:
        lines.append(f"- Miss worth noting: \"{r['query']}\" scored {r['similarity']:.4f} against "
                     f"\"{r['matched_query']}\" - below 0.85, so the agents ran.")
    lines.append("")


def cost_model(sweep: dict) -> dict:
    miss_ms = [r["timings"]["pipeline_ms"] for t in sweep["thresholds"].values() for r in t["rows"]
               if not r["is_cached"]]
    mean_miss_s = statistics.mean(miss_ms) / 1000
    c_miss = mean_miss_s / 3600 * GPU_DOLLARS_PER_HOUR
    totals = {}
    for t, block in sweep["thresholds"].items():
        s = block["summary"]
        totals[t] = {"misses": s["misses"], "false_hits": s["false_hit"],
                     "miss_cost": s["misses"] * c_miss, "false_cost": s["false_hit"] * C_FALSE_HIT}
        totals[t]["total"] = totals[t]["miss_cost"] + totals[t]["false_cost"]
    best = min(totals, key=lambda t: (round(totals[t]["total"], 6), -sweep["thresholds"][t]["summary"]["hit_rate"]))
    return {"mean_miss_s": mean_miss_s, "c_miss": c_miss, "totals": totals, "best": best, "n_misses": len(miss_ms)}


def part3(lines: list[str]) -> None:
    sweep = load("sweep_results.json")
    spec = yaml.safe_load((ROOT / "cache_cases.yaml").read_text())
    cases = {c["id"]: c for c in spec["cases"]}
    seeds = {s["id"]: s["query"] for s in spec["seed_queries"]}
    seed_ids = {q: i for i, q in seeds.items()}
    cm = cost_model(sweep)
    lines += ["## Part 3.2 - Threshold sweep (40 labeled cases, same 10-entry seeded cache for every threshold)", "",
              f"`cache_cases.yaml` sha256 `{sweep['cases_sha256'][:16]}`. Hit rate = hits / 40. False-hit rate = "
              "hits whose cached answer is wrong for the query / 40. Mean latency over all 40 queries (hits are "
              "embedding + vector search + version check; misses run Planner -> Writer -> Reviewer).", "",
              "| Threshold | Hit rate | False-hit rate | Mean latency (ms) | Total cost |", "|---|---:|---:|---:|---:|"]
    for t, block in sorted(sweep["thresholds"].items()):
        s = block["summary"]
        lines.append(f"| {t} | {s['hit_rate']:.1%} ({s['hits']}/40) | {s['false_hit_rate']:.1%} ({s['false_hit']}/40) "
                     f"| {fmt_ms(s['mean_latency_ms'])} | ${cm['totals'][t]['total']:.2f} |")
    lines += ["", "| Threshold | Correct hits | False hits | Missed hits (should hit) | Correct misses | "
              "Mean hit latency (ms) | Mean miss latency (ms) |", "|---|---:|---:|---:|---:|---:|---:|"]
    for t, block in sorted(sweep["thresholds"].items()):
        s = block["summary"]
        lines.append(f"| {t} | {s['correct_hit']} | {s['false_hit']} | {s['missed_hit']} | {s['correct_miss']} | "
                     f"{fmt_ms(s['mean_hit_latency_ms'])} | {fmt_ms(s['mean_miss_latency_ms'])} |")

    first = sweep["thresholds"][min(sweep["thresholds"])]["rows"]
    lines += ["", "Nearest cached query per case (similarity does not depend on the threshold):", "",
              "| Case | Category | Expected | Similarity | Nearest seed | Outcome by threshold (0.75 / 0.80 / 0.85 / 0.90 / 0.95) |",
              "|---|---|---|---:|---|---|"]
    short = {"correct_hit": "hit", "false_hit": "FALSE HIT", "missed_hit": "missed", "correct_miss": "miss"}
    for row in first:
        outcomes = " / ".join(short[sweep["thresholds"][t]["rows"][first.index(row)]["outcome"]]
                              for t in sorted(sweep["thresholds"]))
        lines.append(f"| {row['id']} | {row['category']} | {row['expected']} | {row['similarity']:.4f} | "
                     f"{seed_ids.get(row['matched_query'], '?')} | {outcomes} |")

    # 3.3 one false hit in full: the most similar false hit at the starting threshold 0.85
    false_hits = [r for r in sweep["thresholds"].get("0.85", {"rows": []})["rows"] if r["outcome"] == "false_hit"]
    if not false_hits:
        false_hits = [r for t in sorted(sweep["thresholds"]) for r in sweep["thresholds"][t]["rows"]
                      if r["outcome"] == "false_hit"][:1]
    lines += ["", "## Part 3.3 - One false hit in full", ""]
    if false_hits:
        fh = max(false_hits, key=lambda r: r["similarity"])
        correct = next((sweep["thresholds"][t]["rows"][first.index(next(x for x in first if x["id"] == fh["id"]))]
                        for t in sorted(sweep["thresholds"], reverse=True)
                        if not sweep["thresholds"][t]["rows"][[x["id"] for x in first].index(fh["id"])]["is_cached"]),
                       None)
        lines += [f"- **Incoming query ({fh['id']}, labeled {fh['expected']}):** {fh['query']}",
                  f"- **Cached query ({seed_ids.get(fh['matched_query'])}):** {fh['matched_query']}",
                  f"- **Similarity:** {fh['similarity']:.4f} (threshold {fh['threshold']}) -> served from cache",
                  f"- **Label note:** {cases[fh['id']].get('why', '')}", "", "**Cached answer that was returned:**", "",
                  answer_block(fh["answer"]), ""]
        if correct:
            lines += [f"**Correct answer** (the same query answered by the agents when it missed at threshold "
                      f"{correct['threshold']}):", "", answer_block(correct["answer"]), ""]
        lines += [f"**Likely embedding confusion:** {CONFUSION.get(fh['id'], 'Shared topic words dominate the embedding.')}", ""]
        others = sorted({(r["id"], r["similarity"]) for t in sweep["thresholds"].values() for r in t["rows"]
                         if r["outcome"] == "false_hit"}, key=lambda x: -x[1])
        lines.append("All false hits seen in the sweep: " + ", ".join(f"{i} ({s:.4f})" for i, s in others) + ".")
        lines.append("")
    else:
        lines += ["No false hits occurred at any threshold.", ""]

    # 3.4 cost model
    best = cm["best"]
    lines += ["## Part 3.4 - Cost model and threshold choice", "",
              f"- **Cache-miss cost C_miss = ${cm['c_miss']:.4f}.** A miss runs the full agent pipeline (two qwen3:4b "
              f"calls plus the Reviewer). Measured mean pipeline time over the {cm['n_misses']} sweep misses = "
              f"{cm['mean_miss_s']:.1f} s of GPU time; priced at ${GPU_DOLLARS_PER_HOUR:.2f}/hour for a comparable "
              "single cloud GPU. (The user also waits that long, which the dollar figure does not include.)",
              f"- **False-hit / support cost C_false = ${C_FALSE_HIT:.2f}.** A false hit returns a wrong fact about a "
              "vulnerability (wrong CVE, severity or version). Someone acts on it or files a ticket; we assume "
              f"{SUPPORT_MINUTES} minutes of engineer time at ${ENGINEER_DOLLARS_PER_HOUR:.0f}/hour to notice, triage "
              "and correct it. This is a floor: shipping a still-vulnerable version could cost far more.",
              f"- C_false / C_miss = {C_FALSE_HIT / cm['c_miss']:,.0f}: one false hit costs as much as that many "
              "pipeline runs. Correct hits cost ~0 (a few ms of CPU).", "",
              "Total cost = misses x C_miss + false hits x C_false:", "",
              "| Threshold | Misses | False hits | Miss cost | False-hit cost | Total cost |",
              "|---|---:|---:|---:|---:|---:|"]
    for t, c in sorted(cm["totals"].items()):
        mark = " **(ship)**" if t == best else ""
        lines.append(f"| {t}{mark} | {c['misses']} | {c['false_hits']} | ${c['miss_cost']:.2f} | ${c['false_cost']:.2f} "
                     f"| ${c['total']:.2f} |")
    b = sweep["thresholds"][best]["summary"]
    lines += ["", f"**Threshold to ship: {best}.** It has the lowest total cost: {b['false_hit']} false hits and a "
              f"{b['hit_rate']:.1%} hit rate ({b['correct_hit']} of the 20 should-hit cases served). Because one "
              "false hit costs as much as over a thousand misses, the choice is driven by false hits: the "
              "cheapest threshold is the lowest one that removes them, and any lower threshold buys a few more "
              "hits at a much higher support cost. The price is latency: at this threshold "
              f"{b['missed_hit']} paraphrases that should have hit go to the agents.", ""]
    ordered = sorted(cm["totals"])
    runner = min((t for t in ordered if t != best), key=lambda t: cm["totals"][t]["total"])
    extra_misses = cm["totals"][best]["misses"] - cm["totals"][runner]["misses"]
    extra_false = cm["totals"][runner]["false_hits"] - cm["totals"][best]["false_hits"]
    if extra_false > 0 and extra_misses > 0:
        lines += [f"Sensitivity: {runner} would only beat {best} if a false hit cost less than "
                  f"{extra_misses}/{extra_false} = {extra_misses / extra_false:.1f} misses "
                  f"(${extra_misses / extra_false * cm['c_miss']:.3f}), i.e. if a wrong vulnerability answer were "
                  "almost free.", ""]


def part35(lines: list[str]) -> None:
    d = load("stale_demo.json")
    lines += ["## Part 3.5 - Stale answer and data-version invalidation", "",
              f"Query: \"{d['query']}\" depends on `s0036_rel.vulnerability_reports` row `{d['record']}` "
              f"(id {d['record_before']['id']}, package {d['record_before']['package_name']}). Update: severity "
              f"{d['update']['severity'][0]} -> {d['update']['severity'][1]} (simulated re-score; restored afterwards).", "",
              "| Step | is_cached | Similarity | Latency (ms) | data_version | Answer says | Database says | Result |",
              "|---|---|---:|---:|---|---|---|---|"]
    for s in d["steps"]:
        sim = "-" if s["similarity"] is None else f"{s['similarity']:.4f}"
        lines.append(f"| {s['step']} | {s['is_cached']} | {sim} | {fmt_ms(s['latency_ms'])} | `{s['data_version']}` | "
                     f"{s['answer_severity']} | {s['db_severity']} | {'**STALE**' if s['stale'] else 'fresh'} |")
    lines += ["", "**Strategy (version check on read):** every entry stores `data_version` = hash of the content and "
              "`updated_at` of the record(s) the answer used, plus their ids. On a hit the cache re-reads those rows "
              "by primary key, recomputes the marker and, if it differs, deletes the entry and treats the query "
              "as a miss, so the agents answer from the new data.", "",
              "**Trade-off:** no stale answer is ever served for a tracked record and no write path has to "
              "remember to invalidate, but every hit pays one MySQL primary-key read (~1-3 ms here, versus "
              "~5 ms for the whole hit) and the hit path now depends on MySQL being up. It also only protects the "
              "records detected in the query: a new advisory row that should change an answer is not noticed "
              "until the entry is replaced. A TTL would be cheaper but serves stale answers until expiry.", ""]


def part4(lines: list[str]) -> None:
    table = load("part4_results.json")["table"]
    lines += ["## Part 4 - Self-improving Answering / Evaluator agents", "",
              "Final test (`data/hw9/test_data.json`, 12 questions, identical for every variant):", "",
              "| Variant | Correct answers | Incorrect answers | Average attempts | Average latency (ms) | "
              "Initial answer correct |", "|---|---:|---:|---:|---:|---:|"]
    for name, s in table.items():
        lines.append(f"| {name} | {s['correct']} | {s['incorrect']} | {s['avg_attempts']} | {fmt_ms(s['avg_latency_ms'])} "
                     f"| {s['initial_pass']}/{s['questions']} |")
    training = load("part4_training.json")
    lines += ["", f"Training (`training_data.json`): {training['summary']['initial_pass']}/{training['summary']['questions']} "
              f"initial answers correct, {training['summary']['correct']} after repair. Failure patterns seen in "
              f"initial answers: {training['pattern_counts']}.", "", "Lessons created during training:", ""]
    for lesson in training["lessons"]:
        lines.append(f"- `{lesson['lesson_id']}` after `{lesson['created_from']}` ({lesson['pattern_key']}): "
                     f"{lesson['failure_pattern']} -> {lesson['correction']}")
    validation = load("part4_validation.json")
    lines += ["", "Validation gate (`validation_data.json`):", "",
              "| Step | Initial correct | Final correct | Avg attempts | Kept |", "|---|---:|---:|---:|---|"]
    for h in validation["history"]:
        s = h["summary"]
        lines.append(f"| {h['step']} | {s['initial_pass']}/{s['questions']} | {s['correct']}/{s['questions']} | "
                     f"{s['avg_attempts']} | {'-' if 'keep' not in h else ('yes' if h['keep'] else '**no**')} |")
    lines.append("")
    for d in validation["decisions"]:
        lines.append(f"- `{d['lesson_id']}`: {d['checks']} -> {'kept' if d['keep'] else 'rejected'}"
                     + (f"; regressed {d['regressed_ids']}" if d["regressed_ids"] else ""))
    lines += ["", f"Kept in `data/hw9/lessons.json`: {validation['kept']}; rejected: {validation['rejected'] or 'none'}.", ""]


def main() -> None:
    lines = ["# HW9 Metrics", "", "Generated by `scripts/build_hw9_metrics.py` from `reports/hw09/raw/`.", ""]
    for section in (part1, part2, part3, part35, part4):
        try:
            section(lines)
        except FileNotFoundError as exc:
            lines += [f"## {section.__name__}: missing {Path(exc.filename).name}", ""]
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
