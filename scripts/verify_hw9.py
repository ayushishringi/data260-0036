"""Smoke test for DATA-260 HW9; writes reports/hw09/verification.json.

Needs Redis (make redis-up) and MySQL. Checks behavior, not wording: Redis Stack with the vector
index, every Redis key under the s0036 prefix, the view counter (INCR + MySQL sync every 10),
a cache store/search round trip, cache_cases.yaml unchanged since the sweep, the saved sweep /
stale / Part 2 / Part 4 evidence, dataset hygiene (no expected answers, test set held out),
the unit tests and ruff. No model calls; the counter check restores the row's view_count.

Usage: make verify-hw09
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from backend.database import engine  # noqa: E402
from src.kafka_common import PREFIX, SID4  # noqa: E402
from src.redis_store import ReportCache, get_redis, views_key  # noqa: E402
from src.self_improving import DATA, Reference  # noqa: E402

RAW = ROOT / "reports" / "hw09" / "raw"
OUTPUT = ROOT / "reports" / "hw09" / "verification.json"
checks: list[dict] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"check": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")


def load(name: str) -> dict | list:
    return json.loads((RAW / name).read_text())


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def main() -> None:
    r = get_redis()
    modules = {m[b"name"].decode() for m in r.module_list()}
    check("Redis Stack reachable with the search (vector) module", r.ping() and "search" in modules, sorted(modules))
    keys = [k.decode() for k in r.scan_iter(count=1000)]
    check("every Redis key starts with PREFIX", all(k.startswith(PREFIX) for k in keys),
          f"{len(keys)} keys, prefix {PREFIX}")

    # Part 1: counter on the last HW9 row, restoring its view_count afterwards
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id, view_count FROM vulnerability_reports WHERE report_code = "
                                "'VULN-0036-HW9-23'")).first()
    cache = ReportCache(r)
    saved_redis = r.get(views_key(row.id))
    cache.reset_report_views(row.id)
    counts = [cache.increment_report_views(row.id) for _ in range(12)]
    db_count = cache.database_view_count(row.id)
    with engine.begin() as conn:
        conn.execute(text("UPDATE vulnerability_reports SET view_count = :v WHERE id = :id"),
                     {"v": row.view_count, "id": row.id})
    cache.reset_report_views(row.id)
    if saved_redis is not None:
        r.set(views_key(row.id), saved_redis)
    check("view counter: INCR returns 1..12, MySQL synced at 10", counts == list(range(1, 13)) and db_count == 10,
          {"counts": counts, "db_view_count": db_count, "key": views_key(row.id)})
    part1 = load("part1_counter.json")
    check("saved Part 1 run: 25 accesses, Redis 25, MySQL 20", part1["counts"] == list(range(1, 26))
          and part1["final_redis"] == 25 and part1["final_db"] == 20, part1["key"])

    # Part 2: vector index round trip and saved demo
    from src.semantic_cache import INDEX_NAME, Embedder, SemanticCache
    semantic = SemanticCache(r)
    info = r.ft(INDEX_NAME).info()
    attributes = json.dumps(info["attributes"], default=lambda b: b.decode() if isinstance(b, bytes) else str(b))
    check("vector index uses COSINE over FLOAT32 384-dim embeddings",
          "COSINE" in attributes and "384" in attributes, INDEX_NAME)
    embedder = Embedder()
    vector = embedder.embed(f"verify-hw09 {SID4} probe question")
    key = semantic.store("verify probe", vector, "verify answer", "none", [])
    nearest = semantic.nearest(vector)
    semantic.delete(key)
    check("cache store -> KNN search returns the entry with similarity 1.0",
          nearest is not None and nearest["key"] == key and nearest["similarity"] >= 0.999, nearest and nearest["similarity"])
    demo = load("part2_cache_demo.json")
    kinds = {x["kind"] for x in demo["results"]}
    check("Part 2 demo: >= 10 queries with new, exact duplicate and paraphrase; hits and misses",
          len(demo["results"]) >= 10 and kinds == {"new", "exact duplicate", "paraphrase"}
          and 0 < demo["summary"]["hits"] < len(demo["results"]), demo["summary"])
    check("Part 2 results carry is_cached, similarity and latency_ms",
          all({"is_cached", "similarity", "latency_ms"} <= set(x) for x in demo["results"]))

    # Part 3
    spec = yaml.safe_load((ROOT / "cache_cases.yaml").read_text())
    categories = {c: sum(x["category"] == c for x in spec["cases"]) for c in
                  ("exact_duplicate", "paraphrase", "similar_different", "unrelated")}
    check("cache_cases.yaml: 40 cases, 10 per category", len(spec["cases"]) == 40
          and set(categories.values()) == {10}, categories)
    sweep = load("sweep_results.json")
    sha = hashlib.sha256((ROOT / "cache_cases.yaml").read_bytes()).hexdigest()
    check("cache_cases.yaml unchanged since the sweep ran (sha256)", sweep["cases_sha256"] == sha, sha[:16])
    check("cache_cases.yaml is committed", bool(git("log", "-1", "--format=%h", "--", "cache_cases.yaml")),
          git("log", "-1", "--format=%h %cI", "--", "cache_cases.yaml") or "not committed yet")
    thresholds = sorted(sweep["thresholds"])
    ok = thresholds == ["0.75", "0.80", "0.85", "0.90", "0.95"]
    for t, block in sweep["thresholds"].items():
        rows, s = block["rows"], block["summary"]
        ok &= len(rows) == 40 and s["hits"] == sum(x["is_cached"] for x in rows)
        ok &= s["false_hit"] == sum(x["outcome"] == "false_hit" for x in rows)
        ok &= all(x["is_cached"] == (x["similarity"] >= float(t)) or x.get("stale_invalidated") for x in rows)
    check("sweep: 5 thresholds x 40 cases, summaries match rows, hit iff similarity >= threshold", ok, thresholds)
    stale = load("stale_demo.json")["steps"]
    check("3.5 stale hit: invalidation=none returns the old answer after the update",
          stale[2]["is_cached"] and stale[2]["stale"], [stale[2]["answer_severity"], stale[2]["db_severity"]])
    check("3.5 invalidation=version: marker mismatch -> miss, fresh answer, then a fresh hit",
          not stale[3]["is_cached"] and stale[3]["stale_invalidated"] and not stale[3]["stale"]
          and stale[4]["is_cached"] and not stale[4]["stale"],
          [stale[3]["answer_severity"], stale[4]["answer_severity"]])
    with engine.connect() as conn:
        severity = conn.execute(text("SELECT severity FROM vulnerability_reports WHERE report_code = "
                                     "'VULN-0036-HW9-05'")).scalar()
    check("stale-demo record restored to the reference value", severity == "medium", severity)

    # Part 4
    sets = {n: json.loads((DATA / f"{n}_data.json").read_text()) for n in ("training", "validation", "test")}
    check("input datasets hold only id + question (no expected answers)",
          all(set(x) == {"id", "question"} for items in sets.values() for x in items),
          {n: len(v) for n, v in sets.items()})
    test_q = {x["question"] for x in sets["test"]}
    check("test questions are held out from training and validation",
          not test_q & {x["question"] for n in ("training", "validation") for x in sets[n]})
    reference = Reference()
    check("reference dataset has the ground-truth fields", all(
        {"package", "cve", "severity", "affected_versions", "fixed_version"} <= set(f)
        for f in reference.facts.values()), f"{len(reference.facts)} packages")
    lessons = json.loads((DATA / "lessons.json").read_text())
    check("lessons.json entries have lesson_id, failure_pattern, correction, created_at, use_count", lessons and all(
        {"lesson_id", "failure_pattern", "correction", "created_at", "use_count"} <= set(x) for x in lessons),
          [x["lesson_id"] for x in lessons])
    check("no lesson was created from a test question",
          all(not str(x.get("created_from", "")).startswith("test") for x in lessons))
    controlled = load("part4_controlled.json")
    check("4.1 controlled case: faulty initial answer REVISE -> revised PASS in 2 attempts",
          controlled["attempts"][0]["fault"] == "incomplete" and controlled["initial_result"] == "REVISE"
          and controlled["n_attempts"] == 2 and controlled["final_result"] == "PASS")
    training = load("part4_training.json")["results"]
    reused = [x for x in training if x["lessons_loaded"]]
    check("4.2 lesson created in training and loaded for a later related question",
          any(x["lessons_created"] for x in training) and bool(reused), [x["id"] for x in reused])
    reuse = load("part4_reuse.json")
    check("4.2 reuse demo: kept lesson loaded and its use_count increased", reuse["lessons_loaded"] and all(
        reuse["use_count_after"][x["lesson_id"]] > reuse["use_count_before"][x["lesson_id"]]
        for x in reuse["lessons_loaded"]))
    validation = load("part4_validation.json")
    check("4.3 every candidate lesson has a keep/reject decision from validation_data.json",
          len(validation["decisions"]) == len(load("part4_lessons_candidates.json"))
          and validation["kept"] == [x["lesson_id"] for x in lessons], {"kept": validation["kept"],
                                                                        "rejected": validation["rejected"]})
    table = load("part4_results.json")["table"]
    check("4.4 four variants each ran the 12 test questions", list(table) == [
        "Baseline", "Evaluator Repair", "Lesson Memory", "Validated Improvement"]
          and all(v["questions"] == len(sets["test"]) for v in table.values()),
          {k: (v["correct"], v["avg_attempts"]) for k, v in table.items()})
    check("at most two attempts per question in every run", all(
        x["n_attempts"] <= 2 for name in ("baseline", "evaluator_repair", "lesson_memory", "validated_improvement")
        for x in load(f"part4_test_{name}.json")["results"]))

    tests = subprocess.run([sys.executable, "-m", "unittest", "tests.test_hw9"], cwd=ROOT, capture_output=True,
                           text=True)
    check("unit tests (tests/test_hw9.py)", tests.returncode == 0, tests.stderr.strip().splitlines()[-1])
    files = ["src/redis_store.py", "src/semantic_cache.py", "src/advisory_lookup.py", "src/hw9_pipeline.py",
             "src/self_improving.py", "backend/qa_cache_api.py", "tests/test_hw9.py"] + [
        str(p.relative_to(ROOT)) for p in (ROOT / "scripts").glob("*hw9*.py")]
    lint = subprocess.run([str(ROOT / ".venv" / "bin" / "ruff"), "check", *files], cwd=ROOT, capture_output=True,
                          text=True)
    check("ruff check on HW9 files", lint.returncode == 0, lint.stdout.strip().splitlines()[-1] if lint.stdout else "")

    passed = sum(c["ok"] for c in checks)
    OUTPUT.write_text(json.dumps({"homework": "HW9", "sid4": SID4, "prefix": PREFIX,
                                  "ran_at": datetime.now().isoformat(timespec="seconds"),
                                  "commit": git("rev-parse", "--short", "HEAD"), "passed": passed,
                                  "total": len(checks), "checks": checks}, indent=2, default=str) + "\n")
    print(f"\n{passed}/{len(checks)} checks passed -> {OUTPUT.relative_to(ROOT)}")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
