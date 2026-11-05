"""HW9 Part 3.5: stale cached answer and data-version invalidation.

1. Cache an answer that depends on the s0036_rel record VULN-0036-HW9-05 (requests, severity medium).
2. Update that record (simulated advisory re-score: severity medium -> high).
3. invalidation="none":    the cache returns the old answer (stale hit).
4. invalidation="version": the stored data_version no longer matches the record -> entry deleted,
   agents rerun, fresh answer cached with the new version; the next ask is a fresh hit.
5. The record is restored to the reference value (scripts/migrate_hw9.py) and the cache cleared.
Writes reports/hw09/raw/stale_demo.json.

Usage: make stale-hw09
"""

from __future__ import annotations

import getpass
import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HW8_LOG_DIR", str(ROOT / "reports" / "hw09" / "logs"))

from src import advisory_lookup  # noqa: E402
from src.hw9_pipeline import AgentStack, PipelineClient  # noqa: E402
from src.redis_store import get_redis  # noqa: E402
from src.semantic_cache import CachedQA, Embedder, SemanticCache  # noqa: E402

RAW = ROOT / "reports" / "hw09" / "raw"
RECORD = "VULN-0036-HW9-05"
QUERY = "What is the severity of the requests Proxy-Authorization header leak?"
PARAPHRASE = "How severe is the Proxy-Authorization leak in requests?"
NEW_SEVERITY = "high"


def severity_in(answer: str) -> str:
    """Severity stated by the answer's source-record line."""

    match = re.search(r"severity (critical|high|medium|low)", answer)
    return match.group(1) if match else "?"


def restore() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "migrate_hw9.py")], cwd=ROOT, check=True)


def show(step: str, result: dict, db_severity: str) -> dict:
    sim = "-" if result["similarity"] is None else f"{result['similarity']:.4f}"
    stated = severity_in(result["answer"])
    print(f"{step}\n   is_cached={result['is_cached']} similarity={sim} latency_ms={result['latency_ms']:.1f} "
          f"data_version={result['data_version']}\n   answer says severity={stated}; database says "
          f"severity={db_severity} -> {'STALE' if stated != db_severity else 'fresh'}", flush=True)
    return {"step": step, **result, "answer_severity": stated, "db_severity": db_severity,
            "stale": stated != db_severity}


def main() -> None:
    print(f"user={getpass.getuser()} host={socket.gethostname()} time={datetime.now().isoformat(timespec='seconds')}")
    restore()
    embedder = Embedder()
    cache = SemanticCache(get_redis())
    cache.clear()
    steps = []
    with AgentStack(RAW / "runs" / "stale"):
        pipeline = PipelineClient()
        versioned = CachedQA(cache, embedder, pipeline, invalidation="version", component="stale-demo")
        no_check = CachedQA(cache, embedder, pipeline, invalidation="none", component="stale-demo")
        record = advisory_lookup.find_records(QUERY)[0]
        print(f"\nrecord {RECORD} before: package={record['package_name']} severity={record['severity']} "
              f"updated_at={record['updated_at']} data_version={advisory_lookup.data_version([record])}\n")

        steps.append(show("1. first ask (miss -> agents -> cached)", versioned.ask(QUERY), record["severity"]))
        steps.append(show("2. paraphrase before the update (hit)", versioned.ask(PARAPHRASE), record["severity"]))

        updated = advisory_lookup.update_record(RECORD, severity=NEW_SEVERITY)
        print(f"\nUPDATE vulnerability_reports SET severity='{NEW_SEVERITY}' WHERE report_code='{RECORD}'\n"
              f"record after: severity={updated['severity']} updated_at={updated['updated_at']} "
              f"data_version={advisory_lookup.data_version([updated])}\n")

        steps.append(show("3. invalidation=none -> STALE HIT (old answer returned)", no_check.ask(QUERY),
                          updated["severity"]))
        steps.append(show("4. invalidation=version -> marker mismatch, entry deleted, agents rerun",
                          versioned.ask(QUERY), updated["severity"]))
        steps.append(show("5. invalidation=version, ask again -> fresh hit", versioned.ask(QUERY),
                          updated["severity"]))
        pipeline.close()
    print("\nrestoring the record to the reference value")
    restore()
    cache.clear()
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "stale_demo.json").write_text(json.dumps(
        {"ran_at": datetime.now().isoformat(timespec="seconds"), "record": RECORD, "query": QUERY,
         "paraphrase": PARAPHRASE, "update": {"severity": [record["severity"], NEW_SEVERITY]},
         "record_before": record, "record_after": updated, "steps": steps}, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
