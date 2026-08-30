#!/usr/bin/env python3
"""Planner → Reviewer → Finalizer tag/summary pipeline over a local Ollama model."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from model_client import ModelClient  # noqa: E402


TAGS_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 3,
        },
        "summary": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["tags", "summary"],
}

REVIEWER_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 3,
        },
        "summary": {"type": "string"},
        "changed": {"type": "boolean"},
        "notes": {"type": "string"},
    },
    "required": ["tags", "summary", "changed"],
}

PUBLISH_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 3,
        },
        "summary": {"type": "string"},
    },
    "required": ["tags", "summary"],
}

PLANNER_SYSTEM = """You are Planner, not a parrot.
Given a title and body of text, invent exactly three short topical tags that a librarian would file this document under.
Also write one summary sentence of at most 25 words.
Never copy the title or content fields back into the JSON.
JSON keys: tags, summary, notes."""

REVIEWER_SYSTEM = """You are Reviewer.
You receive the original title/body plus the planner's tags and summary.
Keep a tag only if it appears as a concept in the title or body.
Replace weak tags (too generic like "security" alone, or copied sentences).
If the summary is over 25 words, shorten it.
Set changed=true if you edited tags or summary, else false.
JSON keys: tags, summary, changed, notes."""

FINALIZER_SYSTEM = """You are Finalizer.
Emit the publish JSON: exactly 3 tags and a summary of at most 25 words.
Prefer the reviewer's tags/summary when they are valid.
JSON keys: tags, summary only."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object in model output:\n{text}")
        return json.loads(match.group(0))


def _word_count(summary: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", summary))


def _normalize_publish(payload: dict) -> dict:
    tags = [str(t).strip() for t in payload.get("tags", []) if str(t).strip()]
    tags = tags[:3]
    while len(tags) < 3:
        tags.append(f"topic-{len(tags) + 1}")
    summary = str(payload.get("summary", "")).strip()
    words = re.findall(r"\b[\w'-]+\b", summary)
    if len(words) > 25:
        summary = " ".join(words[:25])
    return {"tags": tags, "summary": summary}


def _has_tags(payload: dict) -> bool:
    tags = payload.get("tags")
    return isinstance(tags, list) and len([t for t in tags if str(t).strip()]) >= 3


def run_pipeline(title: str, content: str, temperature: float, client: ModelClient) -> dict:
    source = f"Title: {title}\n\nBody:\n{content}"

    planner = client.complete(
        [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": source},
        ],
        temperature=temperature,
        format=TAGS_SUMMARY_SCHEMA,
    )
    planner_json = _extract_json(planner.text)
    if not _has_tags(planner_json):
        planner = client.complete(
            [
                {"role": "system", "content": PLANNER_SYSTEM},
                {
                    "role": "user",
                    "content": source + "\n\nYour previous reply was invalid. Return tags[3] and summary only.",
                },
            ],
            temperature=0.0,
            format=TAGS_SUMMARY_SCHEMA,
        )
        planner_json = _extract_json(planner.text)

    reviewer = client.complete(
        [
            {"role": "system", "content": REVIEWER_SYSTEM},
            {
                "role": "user",
                "content": (
                    source
                    + "\n\nPlanner JSON:\n"
                    + json.dumps(planner_json)
                ),
            },
        ],
        temperature=temperature,
        format=REVIEWER_SCHEMA,
    )
    reviewer_json = _extract_json(reviewer.text)
    if not _has_tags(reviewer_json):
        reviewer_json = {
            "tags": planner_json.get("tags", []),
            "summary": planner_json.get("summary", ""),
            "changed": False,
            "notes": "Reviewer JSON missing tags; kept planner output.",
        }

    finalizer = client.complete(
        [
            {"role": "system", "content": FINALIZER_SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {"planner": planner_json, "reviewer": reviewer_json}
                ),
            },
        ],
        temperature=temperature,
        format=PUBLISH_SCHEMA,
    )
    publish = _normalize_publish(_extract_json(finalizer.text))

    return {
        "planner": planner_json,
        "planner_raw": planner.text,
        "reviewer": reviewer_json,
        "reviewer_raw": reviewer.text,
        "publish": publish,
        "tokens": {
            "planner": planner.total_tokens,
            "reviewer": reviewer.total_tokens,
            "finalizer": finalizer.total_tokens,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HW1 Planner/Reviewer/Finalizer demo")
    parser.add_argument("--title")
    parser.add_argument("--content")
    parser.add_argument("--input", type=Path, help="JSON with title and content")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--model", default=None)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.input:
        payload = json.loads(args.input.read_text())
        title = payload["title"]
        content = payload["content"]
    elif args.title and args.content:
        title, content = args.title, args.content
    else:
        parser.error("Provide --title and --content, or --input JSON")

    client = ModelClient(model=args.model) if args.model else ModelClient()
    runs = []
    for i in range(args.repeat):
        started = time.perf_counter()
        result = run_pipeline(title, content, args.temperature, client)
        elapsed_ms = (time.perf_counter() - started) * 1000
        record = {
            "run": i + 1,
            "temperature": args.temperature,
            "latency_ms": round(elapsed_ms, 2),
            "tags": result["publish"]["tags"],
            "summary": result["publish"]["summary"],
            "planner": result["planner"],
            "reviewer": result["reviewer"],
            "publish": result["publish"],
        }
        runs.append(record)
        print("=" * 72)
        print(f"RUN {i + 1}  temp={args.temperature}  latency_ms={elapsed_ms:.1f}")
        print("Planner output:")
        print(json.dumps(result["planner"], indent=2))
        print("Reviewer output:")
        print(json.dumps(result["reviewer"], indent=2))
        print("Finalized / Publish output:")
        print(json.dumps(result["publish"], indent=2))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(runs, indent=2) + "\n")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
