"""HW9: the HW8 agent path used on a cache miss.

PipelineClient sends a question to s0036_inbox and waits for the matching s0036_final message
(same as send_question.py). AgentStack starts planner.py, writer.py and reviewer.py as separate
processes with the HW9 settings (grounded Writer, own consumer groups), unless
HW9_EXTERNAL_AGENTS=1 says they are already running in other terminals.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from src.kafka_common import (
    FINAL_TOPIC,
    INBOX_TOPIC,
    assign_at_end,
    decode,
    make_consumer,
    make_producer,
    now_iso,
    produce_json,
)

ROOT = Path(__file__).resolve().parents[1]
AGENT_ENV = {"HW8_GROUNDED": "1", "HW8_LLM": "1", "HW8_GROUP_SUFFIX": "_hw9",
             "HW8_STATE_DIR": str(ROOT / ".hw8_state" / "hw9")}


class PipelineClient:
    """Ask the Planner -> Writer -> Reviewer pipeline one question and wait for its final answer."""

    def __init__(self) -> None:
        self.producer = make_producer()
        self.reader = make_consumer(f"s0036_hw9_final_reader_{uuid.uuid4().hex[:8]}", offset_reset="latest")
        assign_at_end(self.reader, FINAL_TOPIC)  # only answers produced from now on

    def ask(self, question: str, timeout: float = 300) -> dict[str, Any]:
        """Send the question to s0036_inbox; return the s0036_final message with the same correlation_id."""

        cid = str(uuid.uuid4())
        produce_json(self.producer, INBOX_TOPIC, {"correlation_id": cid, "kind": "question",
                                                  "question": question, "asked_at": now_iso()}, key=cid)
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.reader.poll(1.0)
            if msg is None or msg.error():
                continue
            final = decode(msg)
            if final.get("correlation_id") == cid:
                return final
        raise TimeoutError(f"no final answer for correlation_id {cid} within {timeout}s")

    def close(self) -> None:
        self.reader.close()


class AgentStack:
    """Context manager running the three HW8 agents for a HW9 script."""

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.external = os.getenv("HW9_EXTERNAL_AGENTS", "0") == "1"
        self.procs: list[tuple[subprocess.Popen, Path]] = []
        # New consumer groups per run: a new group starts at the end of each topic, so messages left
        # over from an interrupted earlier run are never replayed into this run's measurements.
        self.group_suffix = f"_hw9_{time.strftime('%Y%m%d%H%M%S')}"

    def __enter__(self) -> "AgentStack":
        if self.external:
            return self
        self.log_dir.mkdir(parents=True, exist_ok=True)
        for agent in ("planner", "writer", "reviewer"):
            path = self.log_dir / f"{agent}.log"
            stream = path.open("a", encoding="utf-8")
            env = {**os.environ, **AGENT_ENV, "HW8_GROUP_SUFFIX": self.group_suffix, "HW8_INSTANCE": agent,
                   "HW8_LOG_DIR": str(self.log_dir / "jsonl")}
            proc = subprocess.Popen([sys.executable, "-u", f"{agent}.py"], cwd=ROOT, env=env,
                                    stdout=stream, stderr=subprocess.STDOUT)
            self.procs.append((proc, path))
        deadline = time.time() + 90
        for proc, path in self.procs:
            while not re.search("Consumer is ready", path.read_text(errors="replace")):
                if time.time() > deadline or proc.poll() is not None:
                    raise RuntimeError(f"agent did not start, see {path}")
                time.sleep(0.3)
        return self

    def __exit__(self, *_exc: object) -> None:
        for proc, _path in self.procs:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()
