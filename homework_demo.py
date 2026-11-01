"""HW8 Part 1 demonstration: CREATE_REPORT then GET_REPORT through Kafka (s0036).

Steps follow the assignment: create a correlation_id, send CREATE_REPORT to s0036_report_requests,
log the worker receiving/processing/replying (read from the worker container's own log), log the
client receiving the response, extract report_id, send GET_REPORT, log the same sequence, and show
the retrieved report with the correlation_id check.

Usage: .venv/bin/python homework_demo.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.kafka_common import REQUEST_TOPIC, RESPONSE_TOPIC, log  # noqa: E402
from src.kafka_rpc import ReportRpcClient  # noqa: E402
from src.report_service import CREATE_OPERATION, GET_OPERATION  # noqa: E402

WORKER_CONTAINER = "s0036-report-worker"
REPORT = {
    "package_name": "lodash",
    "affected_version": "< 4.17.21",
    "severity": "high",
    "description": "Prototype pollution through crafted object keys in merge and set helpers.",
    "submitter_email": "ayushi.shringi@sjsu.edu",
}


def worker_lines(correlation_id: str, since: str) -> list[tuple[datetime, str]]:
    """The worker's log lines for one correlation_id, read from its container."""

    out = subprocess.run(["docker", "logs", "--since", since, WORKER_CONTAINER], capture_output=True, text=True)
    lines = []
    for line in (out.stdout + out.stderr).splitlines():
        if correlation_id in line and "[worker]" in line:
            lines.append((datetime.fromisoformat(line.split(" ", 1)[0]), line))
    return lines


def run_step(client: ReportRpcClient, title: str, operation: str, data: dict) -> dict:
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")
    correlation_id = client.new_correlation_id()
    print(f"[step] created correlation_id = {correlation_id}")
    since = datetime.now().astimezone().isoformat()
    client_records: list[tuple[datetime, str]] = []
    original_log = log

    def capture(component: str, event: str, **fields: object) -> dict:
        record = original_log(component, event, **fields)
        detail = " ".join(f"{k}={json.dumps(v, default=str)}" for k, v in fields.items())
        client_records.append((datetime.fromisoformat(record["ts"]), f"{record['ts']} [{component}] {event} {detail}"))
        return record

    import src.kafka_rpc as rpc_module
    rpc_module.log = capture
    try:
        response = client.request(operation, data, correlation_id)
    finally:
        rpc_module.log = original_log
    time.sleep(0.5)  # let the worker's log reach `docker logs`
    labels = {"SENT request": "1 SEND    ", "RECEIVED request": "2 RECEIVE ", "PROCESSED request": "3 PROCESS ",
              "SENT response": "4 REPLY   ", "RECEIVED response": "5 CLIENT  "}

    def stage(line: str) -> int:
        return next((i for i, k in enumerate(labels) if f"] {k} " in line), 9)

    # time order; lines logged in the same millisecond keep pipeline-stage order
    sequence = sorted(client_records + worker_lines(correlation_id, since),
                      key=lambda item: (item[0], stage(item[1])))
    print(f"\n--- full sequence for correlation_id {correlation_id} (client + worker, time-ordered) ---")
    for _, line in sequence:
        label = next((v for k, v in labels.items() if f"] {k} " in line), "          ")
        print(f"{label}| {line[:400]}")
    preserved = response.get("correlation_id") == correlation_id
    print(f"\nresponse: {json.dumps(response, indent=2)}")
    print(f"correlation_id preserved end to end: {preserved}")
    return response


def main() -> None:
    print(f"HW8 demo - request topic {REQUEST_TOPIC}, response topic {RESPONSE_TOPIC}")
    client = ReportRpcClient(component="client")
    try:
        created = run_step(client, f"STEP A: {CREATE_OPERATION}", CREATE_OPERATION, REPORT)
        if not created.get("success"):
            raise SystemExit(f"CREATE failed: {created}")
        report_id = created["report_id"]
        print(f"\n[step] extracted report_id from the {CREATE_OPERATION} response: {report_id}")
        fetched = run_step(client, f"STEP B: {GET_OPERATION} report_id={report_id}", GET_OPERATION,
                           {"report_id": report_id})
        print(f"\n{'=' * 100}\nRETRIEVED REPORT\n{'=' * 100}")
        print(json.dumps(fetched.get("report"), indent=2))
        print(f"report_id matches the created one: {fetched.get('report', {}).get('report_id') == report_id}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
