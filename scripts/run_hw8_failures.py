"""HW8 Part 2 journey and Part 3 failure experiments (before fix vs after fix).

Spawns real planner/writer/reviewer processes with the HW8_* switches from src/agent_pipeline.py,
injects each failure, and saves evidence to reports/hw08/raw/.

  journey      one question inbox -> final with the local model (Part 2)
  duplicate    replay the same correlation_id; HW8_IDEMPOTENT=0 vs 1
  death        SIGKILL the Writer mid-processing; HW8_COMMIT=before vs after
  poison       a bad task followed by a good one; HW8_RETRY=unbounded vs bounded + dead letter
  ordering     20 VERIFY_SEED messages, 2 partitions, 2 Writers; no key vs key = entity
  all          everything above

Usage: .venv/bin/python scripts/run_hw8_failures.py all
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from confluent_kafka.admin import AdminClient  # noqa: E402

from src.kafka_common import (  # noqa: E402
    BOOTSTRAP,
    DEAD_LETTER_TOPIC,
    DRAFTS_TOPIC,
    FINAL_TOPIC,
    INBOX_TOPIC,
    TASKS_TOPIC,
    VERIFY_SEED,
    assign_at_end,
    decode,
    make_consumer,
    make_producer,
    now_iso,
    produce_json,
)

RAW = ROOT / "reports" / "hw08" / "raw"
RUNS = RAW / "runs"
PYTHON = sys.executable
ENTITIES = ["openssl", "lodash", "log4j-core", "urllib3"]


def banner(title: str) -> None:
    print(f"\n{'=' * 100}\n{title}  ({datetime.now().isoformat(timespec='seconds')})\n{'=' * 100}", flush=True)


def say(text: str) -> None:
    print(f"{now_iso()} [orchestrator] {text}", flush=True)


# ----------------------------------------------------------------------------- helpers


class Proc:
    """One agent process whose stdout goes to a log file we can search."""

    def __init__(self, scenario: str, agent: str, instance: str, **env: str) -> None:
        self.log_path = RUNS / scenario / f"{instance}.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.log_path.open("a", encoding="utf-8")
        full_env = {**os.environ, "HW8_INSTANCE": instance, "HW8_LOG_DIR": str(RUNS / scenario / "jsonl"), **env}
        self.instance = instance
        self.process = subprocess.Popen([PYTHON, "-u", f"{agent}.py"], cwd=ROOT, env=full_env,
                                        stdout=self.stream, stderr=subprocess.STDOUT)
        say(f"started {instance} (pid {self.process.pid}) env={ {k: v for k, v in env.items()} }")

    def text(self) -> str:
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def lines(self, pattern: str) -> list[str]:
        return [line for line in self.text().splitlines() if re.search(pattern, line)]

    def wait_for(self, pattern: str, count: int = 1, timeout: float = 120) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if len(self.lines(pattern)) >= count:
                return True
            time.sleep(0.3)
        return False

    def kill(self) -> None:
        self.process.send_signal(signal.SIGKILL)
        self.process.wait(10)
        say(f"SIGKILL {self.instance} (pid {self.process.pid}) -> exit code {self.process.returncode}")

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(8)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.stream.close()


class Tap:
    """Background reader of a topic from its current end; collects every message."""

    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.messages: list[dict] = []
        self.consumer = make_consumer(f"s0036_tap_{uuid.uuid4().hex[:8]}", offset_reset="latest")
        assign_at_end(self.consumer, topic)
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while self.running:
            msg = self.consumer.poll(0.5)
            if msg is None or msg.error():
                continue
            try:
                value = decode(msg)
            except ValueError:
                value = {"raw": msg.value().decode("utf-8", "replace")}
            self.messages.append({"partition": msg.partition(), "offset": msg.offset(), "value": value})

    def matching(self, cid: str) -> list[dict]:
        return [m for m in self.messages if m["value"].get("correlation_id") == cid]

    def close(self) -> None:
        self.running = False
        self.thread.join(2)
        self.consumer.close()


def committed_offsets(group: str, topic: str) -> dict[int, int]:
    from confluent_kafka import ConsumerGroupTopicPartitions, TopicPartition
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
    parts = [TopicPartition(topic, p) for p in range(2 if topic == TASKS_TOPIC else 1)]
    future = admin.list_consumer_group_offsets([ConsumerGroupTopicPartitions(group, parts)])
    result = list(future.values())[0].result()
    return {tp.partition: tp.offset for tp in result.topic_partitions}


def task_message(cid: str, question: str, plan: object = None) -> dict:
    return {"correlation_id": cid, "kind": "task", "question": question,
            "plan": plan if plan is not None else ["Explain the risk", "Give one example", "List two fixes"],
            "planned_at": now_iso()}


def save(name: str, payload: object) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / name).write_text(json.dumps(payload, indent=2, default=str) + "\n")
    say(f"wrote reports/hw08/raw/{name}")


# ----------------------------------------------------------------------------- Part 2 journey


def journey() -> dict:
    banner("Part 2: one complete message journey inbox -> planner -> writer -> reviewer -> final (local model)")
    suffix = f"_journey_{uuid.uuid4().hex[:4]}"
    procs = [Proc("journey", a, a, HW8_LLM="1", HW8_GROUP_SUFFIX=suffix) for a in ("planner", "writer", "reviewer")]
    try:
        for p in procs:
            p.wait_for("ready and listening", timeout=60)
        final_tap = Tap(FINAL_TOPIC)
        cid = str(uuid.uuid4())
        question = "How should a team respond to a critical CVE found in a transitive dependency?"
        say(f"SENT question to {INBOX_TOPIC} correlation_id={cid}")
        produce_json(make_producer(), INBOX_TOPIC, {"correlation_id": cid, "kind": "question", "question": question,
                                                    "asked_at": now_iso()}, key=cid)
        deadline = time.time() + 600
        while time.time() < deadline and not final_tap.matching(cid):
            time.sleep(1)
        final = final_tap.matching(cid)
        final_tap.close()
        time.sleep(1)
        stages = []
        for p in procs:
            stages += [line for line in p.text().splitlines() if cid in line]
        stages.sort(key=lambda line: line.split(" ", 1)[0])
        print("\n--- journey log lines (all stages, time-ordered) ---")
        for line in stages:
            print(line[:300])
        result = {"correlation_id": cid, "question": question, "final": final[0] if final else None,
                  "stage_log_lines": stages}
        if final:
            print("\n--- final JSON message on s0036_final ---")
            print(json.dumps(final[0]["value"], indent=2))
        save("pipeline_journey.json", result)
        return result
    finally:
        for p in procs:
            p.stop()


# ----------------------------------------------------------------------------- Part 3 duplicate


def duplicate() -> dict:
    out = {}
    for label, idem in (("before_fix", "0"), ("after_fix", "1")):
        banner(f"Part 3 duplicate delivery - {label}: HW8_IDEMPOTENT={idem}, replay the same correlation_id")
        scenario = f"duplicate_{label}"
        suffix = f"_dup_{label}_{uuid.uuid4().hex[:4]}"
        procs = [Proc(scenario, a, a, HW8_LLM="0", HW8_IDEMPOTENT=idem, HW8_GROUP_SUFFIX=suffix)
                 for a in ("planner", "writer", "reviewer")]
        try:
            for p in procs:
                p.wait_for("ready and listening", timeout=60)
            tasks, final = Tap(TASKS_TOPIC), Tap(FINAL_TOPIC)
            cid = str(uuid.uuid4())
            message = {"correlation_id": cid, "kind": "question", "asked_at": now_iso(),
                       "question": "What makes a transitive dependency vulnerability hard to patch?"}
            producer = make_producer()
            say(f"SENT original to {INBOX_TOPIC} correlation_id={cid}")
            produce_json(producer, INBOX_TOPIC, message, key=cid)
            procs[2].wait_for(f"SENT .*{cid}", timeout=60)
            say(f"REPLAY: same message, same correlation_id={cid}")
            produce_json(producer, INBOX_TOPIC, message, key=cid)
            procs[0].wait_for(f"RECEIVED .*{cid}", count=2, timeout=60)
            time.sleep(6)
            tasks.close()
            final.close()
            counts = {"inbox_messages_sent": 2, "tasks_produced": len(tasks.matching(cid)),
                      "final_messages": len(final.matching(cid)),
                      "duplicates_skipped": sum(len(p.lines(f"DUPLICATE skipped .*{cid}")) for p in procs)}
            say(f"{label}: {counts}")
            out[label] = {"correlation_id": cid, **counts,
                          "log": [line for p in procs for line in p.text().splitlines() if cid in line]}
        finally:
            for p in procs:
                p.stop()
    save("failure_duplicate.json", out)
    return out


# ----------------------------------------------------------------------------- Part 3 consumer death


def death() -> dict:
    out = {}
    for label, commit in (("before_fix", "before"), ("after_fix", "after")):
        banner(f"Part 3 consumer death - {label}: HW8_COMMIT={commit}; SIGKILL Writer mid-processing, restart it")
        scenario = f"death_{label}"
        suffix = f"_death_{label}_{uuid.uuid4().hex[:4]}"
        group = f"s0036_writers{suffix}"
        writer = Proc(scenario, "writer", "writer-run1", HW8_LLM="0", HW8_COMMIT=commit, HW8_SLOW_SECONDS="20",
                      HW8_GROUP_SUFFIX=suffix)
        writer.wait_for("ready and listening", timeout=60)
        drafts = Tap(DRAFTS_TOPIC)
        cid = str(uuid.uuid4())
        sent = produce_json(make_producer(), TASKS_TOPIC, task_message(cid, "Why pin dependency versions?"), key=cid)
        say(f"SENT task correlation_id={cid} to {TASKS_TOPIC} partition={sent['partition']} offset={sent['offset']}")
        writer.wait_for(f"STARTED long processing .*{cid}", timeout=60)
        time.sleep(2)
        writer.kill()
        offsets_after_kill = committed_offsets(group, TASKS_TOPIC)
        say(f"committed offsets for {group} after the kill: {offsets_after_kill} (task is at offset {sent['offset']})")
        restarted = Proc(scenario, "writer", "writer-run2", HW8_LLM="0", HW8_COMMIT=commit, HW8_GROUP_SUFFIX=suffix)
        restarted.wait_for("ready and listening", timeout=90)
        redelivered = restarted.wait_for(f"RECEIVED .*{cid}", timeout=30)
        time.sleep(4)
        drafts.close()
        offsets_end = committed_offsets(group, TASKS_TOPIC)
        result = {"correlation_id": cid, "task_partition": sent["partition"], "task_offset": sent["offset"],
                  "committed_after_kill": offsets_after_kill, "committed_at_end": offsets_end,
                  "redelivered_after_restart": redelivered, "drafts_produced": len(drafts.matching(cid)),
                  "log_run1": [line for line in writer.text().splitlines() if cid in line or "COMMITTED" in line],
                  "log_run2": restarted.text().splitlines()[-8:]}
        say(f"{label}: redelivered={redelivered} drafts_produced={result['drafts_produced']} "
            f"committed_after_kill={offsets_after_kill} committed_at_end={offsets_end}")
        out[label] = result
        restarted.stop()
        writer.stop()
    save("failure_consumer_death.json", out)
    return out


# ----------------------------------------------------------------------------- Part 3 poison


def poison() -> dict:
    out = {}
    for label, retry in (("before_fix", "unbounded"), ("after_fix", "bounded")):
        banner(f"Part 3 poison message - {label}: HW8_RETRY={retry}; a bad task, then a good task, same partition")
        scenario = f"poison_{label}"
        suffix = f"_poison_{label}_{uuid.uuid4().hex[:4]}"
        writer = Proc(scenario, "writer", "writer", HW8_LLM="0", HW8_RETRY=retry, HW8_MAX_RETRIES="3",
                      HW8_GROUP_SUFFIX=suffix)
        writer.wait_for("ready and listening", timeout=60)
        drafts, dead = Tap(DRAFTS_TOPIC), Tap(DEAD_LETTER_TOPIC)
        producer = make_producer()
        bad, good = f"poison-{uuid.uuid4().hex[:8]}", str(uuid.uuid4())
        key = "poison-demo"  # same key -> same partition, so the bad message is in front of the good one
        produce_json(producer, TASKS_TOPIC, task_message(bad, "malformed task", plan="this-is-not-a-list"), key=key)
        produce_json(producer, TASKS_TOPIC, task_message(good, "What is an SBOM?"), key=key)
        say(f"SENT bad task {bad} then good task {good} with key={key}")
        good_done = writer.wait_for(f"SENT .*{good}", timeout=25)
        time.sleep(2)
        drafts.close()
        dead.close()
        result = {"bad_correlation_id": bad, "good_correlation_id": good,
                  "attempts_on_bad_message": len(writer.lines(f"PROCESSING FAILED .*{bad}")),
                  "moved_to_dead_letter": len(dead.matching(bad)),
                  "dead_letter_record": dead.matching(bad)[0]["value"] if dead.matching(bad) else None,
                  "good_message_processed_within_25s": good_done,
                  "good_drafts": len(drafts.matching(good)),
                  "log": [line for line in writer.text().splitlines() if bad in line or good in line]}
        say(f"{label}: attempts={result['attempts_on_bad_message']} dead_letter={result['moved_to_dead_letter']} "
            f"good_processed={good_done}")
        out[label] = result
        writer.stop()
    save("failure_poison.json", out)
    return out


# ----------------------------------------------------------------------------- Part 3 ordering


def ordering_messages() -> list[dict]:
    rng = random.Random(VERIFY_SEED)
    seq = {e: 0 for e in ENTITIES}
    messages = []
    for index in range(20):
        entity = rng.choice(ENTITIES)
        seq[entity] += 1
        probe_id = f"probe-{VERIFY_SEED}-{index:02d}"
        messages.append({"correlation_id": probe_id, "probe_id": probe_id, "kind": "ordering_probe", "index": index,
                         "entity": entity, "seq": seq[entity],
                         "update": f"{entity} advisory update #{seq[entity]}"})
    return messages


def ordering() -> dict:
    messages = ordering_messages()
    save("ordering_messages_verify_seed.json", {"verify_seed": VERIFY_SEED, "messages": messages})
    out = {}
    for label, keyed in (("run1_no_key", False), ("run2_key_entity", True)):
        banner(f"Part 3 ordering - {label}: 20 messages, {TASKS_TOPIC} has 2 partitions, 2 Writers in one group")
        scenario = f"ordering_{label}"
        suffix = f"_order_{label}_{uuid.uuid4().hex[:4]}"
        writers = [Proc(scenario, "writer", f"writer-{n}", HW8_LLM="0", HW8_GROUP_SUFFIX=suffix) for n in "AB"]
        for w in writers:
            w.wait_for("ready and listening", timeout=60)
        time.sleep(4)  # let the group settle so each Writer owns one partition
        for w in writers:
            say(f"{w.instance} assignment: {w.lines('ready and listening')[-1].split('partitions=')[1].split(' ')[0]}")
        # no key: random partition per message (sticky batching off); key: hash(entity) -> one partition
        producer = make_producer(**({} if keyed else {"sticky.partitioning.linger.ms": 0}))
        sent = []
        for m in messages:
            meta = produce_json(producer, TASKS_TOPIC, m, key=m["entity"] if keyed else None)
            sent.append({**m, **meta})
        say(f"SENT 20 messages ({'key=entity' if keyed else 'no key'})")
        deadline = time.time() + 90
        while time.time() < deadline and sum(len(w.lines("PROCESSED ordering probe")) for w in writers) < 20:
            time.sleep(0.5)
        time.sleep(1)
        rows = []
        for w in writers:
            for line in w.lines("PROCESSED ordering probe"):
                ts = line.split(" ", 1)[0]
                probe = re.search(r'probe_id="([^"]+)"', line).group(1)
                rows.append({"processed_at": ts, "writer": w.instance, "probe_id": probe})
        by_probe = {s["probe_id"]: s for s in sent}
        rows.sort(key=lambda r: r["processed_at"])
        for order, row in enumerate(rows, 1):
            s = by_probe[row["probe_id"]]
            row.update(processed_order=order, sent_index=s["index"], entity=s["entity"], seq=s["seq"],
                       partition=s["partition"], offset=s["offset"])
        violations = []
        for entity in ENTITIES:
            seqs = [r["seq"] for r in rows if r["entity"] == entity]
            partitions = sorted({r["partition"] for r in rows if r["entity"] == entity})
            if seqs != sorted(seqs):
                violations.append({"entity": entity, "processed_seq_order": seqs, "partitions": partitions})
        per_entity = {e: {"processed_seq_order": [r["seq"] for r in rows if r["entity"] == e],
                          "partitions": sorted({r["partition"] for r in rows if r["entity"] == e})}
                      for e in ENTITIES}
        path = RAW / f"ordering_{label}.csv"
        with path.open("w", newline="") as stream:
            writer_csv = csv.DictWriter(stream, fieldnames=["processed_order", "processed_at", "writer", "probe_id",
                                                            "sent_index", "entity", "seq", "partition", "offset"])
            writer_csv.writeheader()
            writer_csv.writerows(rows)
        print(f"\n{'order':>5} {'writer':9} {'partition':>9} {'entity':11} {'seq':>3} sent_index")
        for r in rows:
            print(f"{r['processed_order']:>5} {r['writer']:9} {r['partition']:>9} {r['entity']:11} {r['seq']:>3} "
                  f"{r['sent_index']}")
        print("\nper entity (processing order of seq, partitions used):")
        for e, v in per_entity.items():
            ok = v["processed_seq_order"] == sorted(v["processed_seq_order"])
            print(f"  {e:11} seq={v['processed_seq_order']} partitions={v['partitions']} "
                  f"{'in order' if ok else 'OUT OF ORDER'}")
        say(f"{label}: processed={len(rows)} entities_out_of_order={len(violations)} -> wrote {path.name}")
        out[label] = {"processed": len(rows), "per_entity": per_entity, "violations": violations,
                      "csv": f"reports/hw08/raw/{path.name}"}
        for w in writers:
            w.stop()
    save("failure_ordering.json", out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("what", choices=["journey", "duplicate", "death", "poison", "ordering", "all"])
    args = parser.parse_args()
    steps = ["journey", "duplicate", "death", "poison", "ordering"] if args.what == "all" else [args.what]
    for step in steps:
        globals()[step]()


if __name__ == "__main__":
    main()
