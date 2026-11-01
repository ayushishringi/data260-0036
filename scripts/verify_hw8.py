"""Smoke test for DATA-260 HW8; writes reports/hw08/verification.json.

Needs the Docker stack running (docker compose -f docker-compose.hw8.yml up -d). Checks behavior,
not wording: containers up, topics and partitions, CREATE_REPORT -> GET_REPORT round trip through
Kafka with correlation_id preserved, error responses, the FastAPI wrapper on PORT_BASE, a full
Planner -> Writer -> Reviewer journey, idempotent replay, and the saved Part 3 evidence.
Agent state and logs go to a temporary directory; no application code is modified.

Usage: make verify-hw08
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="verify_hw08_")
os.environ.setdefault("HW8_LOG_DIR", TMP)

from src.kafka_common import (  # noqa: E402
    FINAL_TOPIC,
    INBOX_TOPIC,
    PORT_BASE,
    PREFIX,
    SEED,
    SID4,
    TOPIC_PARTITIONS,
    VERIFY_SEED,
    decode,
    make_consumer,
    make_producer,
    produce_json,
    topic_partitions,
)
from src.kafka_rpc import ReportRpcClient  # noqa: E402

RAW = ROOT / "reports" / "hw08" / "raw"
OUTPUT = ROOT / "reports" / "hw08" / "verification.json"
CONTAINERS = ("s0036-kafka", "s0036-report-worker", "s0036-api")
REPORT = {"package_name": f"verify-hw08-{VERIFY_SEED}", "affected_version": "< 1.0.0", "severity": "low",
          "description": "Temporary report created by the HW8 verification script.",
          "submitter_email": "verify@example.edu"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def http(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(f"http://127.0.0.1:{PORT_BASE}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status, json.loads(response.read())


def final_messages(cid: str, wait: float) -> list[dict]:
    reader = make_consumer(f"s0036_verify_{uuid.uuid4().hex[:8]}", offset_reset="earliest")
    from confluent_kafka import TopicPartition
    reader.assign([TopicPartition(FINAL_TOPIC, 0, 0)])
    found, deadline = [], time.time() + wait
    while time.time() < deadline:
        msg = reader.poll(0.5)
        if msg is not None and not msg.error() and decode(msg).get("correlation_id") == cid:
            found.append(decode(msg))
    reader.close()
    return found


def main() -> int:
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: object = None) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        print(f"{'PASS' if passed else 'FAIL'}  {name}", flush=True)

    running = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
    check("docker: Kafka, worker and FastAPI containers running", all(c in running for c in CONTAINERS),
          [c for c in CONTAINERS if c not in running])
    worker_log = subprocess.run(["docker", "logs", "s0036-report-worker"], capture_output=True, text=True)
    check("worker log contains 'Consumer is ready and listening...'",
          "Consumer is ready and listening..." in worker_log.stdout + worker_log.stderr)

    partitions = topic_partitions()
    check("all 7 s0036_* topics exist with the expected partition counts",
          all(partitions.get(t) == n for t, n in TOPIC_PARTITIONS.items()), partitions)

    client = ReportRpcClient(component="verify")
    try:
        cid = client.new_correlation_id()
        created = client.request("CREATE_REPORT", REPORT, cid)
        check("CREATE_REPORT over Kafka returns success + UUID report_id, correlation_id preserved",
              created.get("success") is True and len(created.get("report_id", "")) == 36
              and created.get("correlation_id") == cid)
        cid2 = client.new_correlation_id()
        fetched = client.request("GET_REPORT", {"report_id": created.get("report_id")}, cid2)
        check("GET_REPORT round-trips the created report, correlation_id preserved",
              fetched.get("success") is True and fetched.get("report", {}).get("package_name") ==
              REPORT["package_name"] and fetched.get("correlation_id") == cid2)
        cid3 = client.new_correlation_id()
        missing = client.request("GET_REPORT", {"report_id": str(uuid.uuid4())}, cid3)
        check("GET_REPORT unknown id -> success false + error, correlation_id preserved",
              missing.get("success") is False and missing.get("error") and missing.get("correlation_id") == cid3)
        cid4 = client.new_correlation_id()
        unknown = client.request("DROP_REPORT", {}, cid4)
        check("unknown operation -> success false + error, correlation_id preserved",
              unknown.get("success") is False and unknown.get("correlation_id") == cid4)
        invalid = client.request("CREATE_REPORT", {**REPORT, "severity": "urgent", "package_name": ""})
        check("CREATE_REPORT with invalid fields is rejected", invalid.get("success") is False)
    finally:
        client.close()

    try:
        api_cid = f"verify-api-{uuid.uuid4().hex[:8]}"
        status, created = http("POST", "/api/kafka/reports", REPORT, {"X-Correlation-ID": api_cid})
        _, fetched = http("GET", f"/api/kafka/reports/{created.get('report_id')}")
        check(f"FastAPI on 127.0.0.1:{PORT_BASE}: create + get through Kafka, X-Correlation-ID preserved",
              status == 200 and created.get("correlation_id") == api_cid and fetched.get("success") is True)
    except Exception as exc:  # API not reachable
        check(f"FastAPI on 127.0.0.1:{PORT_BASE}: create + get through Kafka, X-Correlation-ID preserved", False,
              str(exc))

    env = {**os.environ, "HW8_LLM": "0", "HW8_STATE_DIR": TMP, "HW8_GROUP_SUFFIX": f"_verify_{uuid.uuid4().hex[:6]}"}
    procs = [subprocess.Popen([sys.executable, "-u", f"{a}.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL) for a in ("planner", "writer", "reviewer")]
    try:
        time.sleep(12)
        cid = str(uuid.uuid4())
        message = {"correlation_id": cid, "kind": "question", "question": "Why should dependency scans be repeated?"}
        producer = make_producer()
        produce_json(producer, INBOX_TOPIC, message, key=cid)
        first = final_messages(cid, 30)
        check("pipeline: inbox -> planner -> writer -> reviewer -> final, same correlation_id, status + answer",
              len(first) == 1 and first[0].get("status") in ("approved", "needs_revision") and first[0].get("answer"))
        produce_json(producer, INBOX_TOPIC, message, key=cid)
        check("pipeline: replaying the same correlation_id adds no second final message",
              len(final_messages(cid, 15)) == 1)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(8)
            except subprocess.TimeoutExpired:
                p.kill()

    def raw(name: str) -> dict:
        path = RAW / name
        return json.loads(path.read_text()) if path.exists() else {}

    dup, death, poison, order = (raw("failure_duplicate.json"), raw("failure_consumer_death.json"),
                                 raw("failure_poison.json"), raw("failure_ordering.json"))
    check("Part 3 evidence: duplicate replay 2 finals before fix, 1 after",
          dup.get("before_fix", {}).get("final_messages") == 2 and dup.get("after_fix", {}).get("final_messages") == 1)
    check("Part 3 evidence: killed Writer loses the task before fix, redelivers + completes after",
          death.get("before_fix", {}).get("drafts_produced") == 0
          and death.get("after_fix", {}).get("redelivered_after_restart") is True
          and death.get("after_fix", {}).get("drafts_produced") == 1)
    check("Part 3 evidence: poison blocks before fix; after fix 3 attempts -> dead letter, next message processed",
          poison.get("before_fix", {}).get("good_message_processed_within_25s") is False
          and poison.get("after_fix", {}).get("attempts_on_bad_message") == 3
          and poison.get("after_fix", {}).get("moved_to_dead_letter") == 1
          and poison.get("after_fix", {}).get("good_message_processed_within_25s") is True)
    check("Part 3 evidence: keyed run keeps every entity in one partition and in order",
          order.get("run2_key_entity", {}).get("violations") == []
          and all(len(v["partitions"]) == 1 for v in order.get("run2_key_entity", {}).get("per_entity", {}).values()))

    files = ["src/kafka_common.py", "src/kafka_rpc.py", "src/report_service.py", "src/agent_pipeline.py",
             "backend/report_kafka_api.py", "report_worker.py", "homework_demo.py", "planner.py", "writer.py",
             "reviewer.py", "send_question.py", "scripts/run_hw8_failures.py", "scripts/verify_hw8.py",
             "tests/test_hw8.py"]
    lint = subprocess.run([str(ROOT / ".venv/bin/ruff"), "check", *files], cwd=ROOT, capture_output=True, text=True)
    check("ruff passes on HW8 code", lint.returncode == 0, lint.stdout.strip().splitlines()[-1:])
    tests = subprocess.run([sys.executable, "-m", "unittest", "tests.test_hw8"], cwd=ROOT, capture_output=True,
                           text=True)
    check("unit tests (tests/test_hw8.py) pass", tests.returncode == 0, tests.stderr.strip().splitlines()[-1:])

    result = {
        "homework": 8,
        "SID4": SID4,
        "PORT_BASE": PORT_BASE,
        "PREFIX": PREFIX,
        "SEED": SEED,
        "VERIFY_SEED": VERIFY_SEED,
        "commit": git("rev-parse", "HEAD") or "uncommitted",
        "tag_hw8_commit": git("rev-parse", "hw8^{commit}") or "missing",
        "working_tree_clean": git("status", "--porcelain", "--", "src", "backend", "scripts", "tests", "*.py") == "",
        "model": "qwen3:4b via local Ollama for Planner/Writer (verify uses HW8_LLM=0 template mode)",
        "configuration": {"kafka": "apache/kafka:3.9.0 KRaft single broker", "topics": TOPIC_PARTITIONS,
                          "max_retries": 3, "commit": "after successful processing"},
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{sum(c['passed'] for c in checks)}/{len(checks)} checks passed -> {OUTPUT.relative_to(ROOT)}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
