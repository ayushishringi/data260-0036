"""Memory operations used by the HW6 chat endpoint."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pymongo.collection import Collection

from backend.hw6_mongo_database import (
    get_episodes_collection,
    get_messages_collection,
    get_summaries_collection,
)
from backend.hw6_file_memory import (
    compact_memory,
    consolidation_required,
    file_memory_context,
    handle_file_memory_command,
)
from src.model_client import ModelClient


SHORT_TERM_N = int(os.getenv("SHORT_TERM_N", "12"))
SUMMARIZE_EVERY_USER_MSGS = int(os.getenv("SUMMARIZE_EVERY_USER_MSGS", "5"))
LIFETIME_SUMMARIZE_EVERY_SESSION_SUMMARIES = int(
    os.getenv("LIFETIME_SUMMARIZE_EVERY_SESSION_SUMMARIES", "2")
)
EPISODIC_TOP_K = int(os.getenv("EPISODIC_TOP_K", "3"))
# "window" keeps the last SHORT_TERM_N messages verbatim. "compressed_window"
# keeps the same messages but shortens every assistant reply except the latest
# one to COMPRESSED_REPLY_CHARS characters (the session summary carries the rest).
MEMORY_POLICY = os.getenv("MEMORY_POLICY", "window")
COMPRESSED_REPLY_CHARS = int(os.getenv("COMPRESSED_REPLY_CHARS", "240"))
REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "hw06" / "raw"
CHAT_COSTS_PATH = REPORTS_DIR / "chat_costs.jsonl"
SYSTEM_PRIMER = (
    "You are a helpful assistant. Use the supplied memory as context, "
    "but do not claim to remember anything that is not present. "
    "Answer concisely, in under 150 words."
)
IMPORTANCE_PERSONAL_RE = re.compile(r"\b(i|i'm|my|our|we|we're|me|us)\b")
IMPORTANCE_DURABLE_RE = re.compile(
    r"\b(always|never|must|deadline|prefer|prefers|owns|uses|use|scheduled|reviewer|reviews|lead|version)\b"
)


def memory_config() -> dict[str, Any]:
    """Return the memory settings this server process is actually using."""

    return {
        "short_term_n": SHORT_TERM_N,
        "memory_policy": MEMORY_POLICY,
        "summarize_every_user_msgs": SUMMARIZE_EVERY_USER_MSGS,
        "episodic_top_k": EPISODIC_TOP_K,
    }


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def log_chat_cost(record: dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with CHAT_COSTS_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, default=str) + "\n")


def save_message(
    user_id: str,
    session_id: str | None,
    role: str,
    content: str,
) -> dict[str, Any]:
    document = {
        "user_id": user_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": now_utc(),
    }
    result = get_messages_collection().insert_one(document)
    document["_id"] = result.inserted_id
    return document


def load_short_term_messages(user_id: str, session_id: str | None) -> list[dict[str, Any]]:
    query = {"user_id": user_id, "session_id": session_id}
    rows = list(
        get_messages_collection()
        .find(query)
        .sort("created_at", -1)
        .limit(SHORT_TERM_N)
    )
    rows = list(reversed(rows))
    if MEMORY_POLICY == "compressed_window":
        rows = compress_window(rows)
    return rows


def compress_window(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shorten older assistant replies; user messages are kept verbatim."""

    assistant_indexes = [index for index, row in enumerate(rows) if row["role"] == "assistant"]
    keep_full = assistant_indexes[-1] if assistant_indexes else None
    compressed = []
    for index, row in enumerate(rows):
        content = row["content"]
        if row["role"] == "assistant" and index != keep_full and len(content) > COMPRESSED_REPLY_CHARS:
            content = content[:COMPRESSED_REPLY_CHARS].rsplit(" ", 1)[0] + " [...]"
        compressed.append({**row, "content": content})
    return compressed


def load_latest_summaries(user_id: str, session_id: str | None) -> dict[str, Any]:
    collection = get_summaries_collection()
    session = collection.find_one(
        {"user_id": user_id, "scope": "session", "session_id": session_id},
        sort=[("created_at", -1)],
    )
    lifetime = collection.find_one(
        {"user_id": user_id, "scope": "user", "session_id": None},
        sort=[("created_at", -1)],
    )
    return {"session": session, "user": lifetime}


def load_messages_since_last_summary(
    user_id: str,
    session_id: str | None,
) -> list[dict[str, Any]]:
    """Load the full unsummarized session segment for summarization."""

    summary = get_summaries_collection().find_one(
        {"user_id": user_id, "session_id": session_id, "scope": "session"},
        sort=[("created_at", -1)],
    )
    query: dict[str, Any] = {"user_id": user_id, "session_id": session_id}
    if summary and summary.get("created_at"):
        query["created_at"] = {"$gt": summary["created_at"]}
    return list(get_messages_collection().find(query).sort("created_at", 1))


def _hash_embedding(text: str, dimensions: int = 64) -> list[float]:
    values = np.zeros(dimensions, dtype=np.float32)
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        values[index] += 1.0 if digest[4] % 2 else -1.0
    norm = float(np.linalg.norm(values))
    return (values / norm if norm else values).astype(float).tolist()


def embed_text(text: str) -> list[float]:
    """Create a local embedding, falling back to a deterministic vector."""

    try:
        from sentence_transformers import SentenceTransformer

        if not hasattr(embed_text, "_model"):
            embed_text._model = SentenceTransformer("all-MiniLM-L6-v2")
        return embed_text._model.encode(text, normalize_embeddings=True).astype(float).tolist()
    except Exception:
        return _hash_embedding(text)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    left_array = np.asarray(left, dtype=float)
    right_array = np.asarray(right, dtype=float)
    denominator = np.linalg.norm(left_array) * np.linalg.norm(right_array)
    return float(np.dot(left_array, right_array) / denominator) if denominator else 0.0


def retrieve_episodes(user_id: str, query: str) -> list[dict[str, Any]]:
    query_embedding = embed_text(query)
    scored: list[tuple[float, dict[str, Any]]] = []
    for episode in get_episodes_collection().find({"user_id": user_id}):
        score = cosine_similarity(query_embedding, episode.get("embedding", []))
        scored.append((score, episode))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [{**episode, "similarity": score} for score, episode in scored[:EPISODIC_TOP_K]]


def score_importance(fact: str) -> float:
    """Heuristic 0..1 importance: personal, specific, durable statements score higher."""

    text = fact.casefold()
    score = 0.3
    if IMPORTANCE_PERSONAL_RE.search(text):
        score += 0.3
    if re.search(r"\d", text):
        score += 0.2
    if IMPORTANCE_DURABLE_RE.search(text):
        score += 0.2
    return round(min(score, 1.0), 2)


def extract_episodes(user_id: str, session_id: str | None, message: str) -> list[dict[str, Any]]:
    """Store up to 3 declarative sentences from a user message as scored episodic facts.

    Questions are not facts, so they are skipped.
    """

    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", message) if part.strip()]
    candidates = [
        sentence.rstrip(".!").strip()
        for sentence in sentences
        if not sentence.endswith("?") and len(sentence.split()) >= 3
    ]
    scored = sorted(
        ((score_importance(fact), fact) for fact in candidates),
        key=lambda item: item[0],
        reverse=True,
    )[:3]
    collection = get_episodes_collection()
    saved = []
    for importance, fact in scored:
        if len(fact) > 200:
            fact = fact[:197] + "..."
        document = {
            "user_id": user_id,
            "session_id": session_id,
            "fact": fact,
            "importance": float(importance),
            "embedding": embed_text(fact),
            "created_at": now_utc(),
        }
        result = collection.insert_one(document)
        document["_id"] = result.inserted_id
        saved.append(document)
    return saved


def _summary_text(messages: list[dict[str, Any]], model_client: ModelClient) -> str:
    # Assistant replies are truncated so the summary records what the user said,
    # not the model's long answers.
    transcript = "\n".join(
        f"{item['role']}: {item['content'] if item['role'] == 'user' else item['content'][:300]}"
        for item in messages
    )
    result = model_client.complete([
        {
            "role": "system",
            "content": (
                "You write memory notes for a chat assistant. Summarize the transcript as 3-6 short "
                "bullet points. Record every concrete fact the user stated (names, versions, numbers, "
                "dates, tools) and list the topics discussed. Do not answer questions and do not add advice."
            ),
        },
        {"role": "user", "content": f"Transcript:\n{transcript}"},
    ])
    return result.text


def maybe_summarize(
    user_id: str,
    session_id: str | None,
    model_client: ModelClient,
) -> None:
    user_count = get_messages_collection().count_documents({
        "user_id": user_id,
        "session_id": session_id,
        "role": "user",
    })
    if user_count == 0 or user_count % SUMMARIZE_EVERY_USER_MSGS != 0:
        return
    messages = load_messages_since_last_summary(user_id, session_id)
    text = _summary_text(messages, model_client)
    collection = get_summaries_collection()
    collection.insert_one({
        "user_id": user_id,
        "session_id": session_id,
        "scope": "session",
        "text": text,
        "created_at": now_utc(),
    })
    session_summaries = list(collection.find({
        "user_id": user_id,
        "scope": "session",
    }).sort("created_at", -1))
    if len(session_summaries) % LIFETIME_SUMMARIZE_EVERY_SESSION_SUMMARIES != 0:
        return
    lifetime_input = "\n\n".join(item["text"] for item in session_summaries)
    lifetime_result = model_client.complete([
        {
            "role": "system",
            "content": (
                "Condense these session summaries into at most 8 lifetime memory bullets. "
                "Keep every concrete fact the user stated. Do not add advice."
            ),
        },
        {"role": "user", "content": lifetime_input},
    ])
    collection.insert_one({
        "user_id": user_id,
        "session_id": None,
        "scope": "user",
        "text": lifetime_result.text,
        "created_at": now_utc(),
    })


def assemble_prompt(
    user_message: str,
    short_term: list[dict[str, Any]],
    summaries: dict[str, Any],
    episodes: list[dict[str, Any]],
) -> list[dict[str, str]]:
    long_term = "\n".join(
        item["text"] for item in (summaries.get("user"), summaries.get("session")) if item
    ) or "(none)"
    episode_text = "\n".join(f"- {item['fact']}" for item in episodes) or "(none)"
    context = (
        f"Lifetime/session summaries:\n{long_term}\n\n"
        f"Relevant episodic facts:\n{episode_text}"
    )
    messages = [{
        "role": "system",
        "content": SYSTEM_PRIMER + "\n\nFile-based memory:\n" + file_memory_context() + "\n\n" + context,
    }]
    messages.extend({"role": item["role"], "content": item["content"]} for item in short_term)
    messages.append({"role": "user", "content": user_message})
    return messages


def public_summary(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    result = dict(summary)
    if "_id" in result:
        result["_id"] = str(result["_id"])
    return result


def make_chat_turn(
    user_id: str,
    session_id: str | None,
    user_message: str,
    model_client: ModelClient,
) -> dict[str, Any]:
    started = time.perf_counter()
    command_result = handle_file_memory_command(
        user_message,
        user_id,
        session_id,
        model_client,
    )
    if command_result is not None:
        save_message(user_id, session_id, "user", user_message)
        reply = command_result.get("message", "")
        save_message(user_id, session_id, "assistant", reply)
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        return {
            "reply": reply,
            "file_memory": command_result,
            "used": {"short_term_messages": [], "long_term_summary": None, "episodic_facts": []},
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "latency_ms": latency_ms,
                "component_token_estimates": {},
            },
        }
    auto_compaction = compact_memory() if consolidation_required() else None
    save_message(user_id, session_id, "user", user_message)
    short_term = load_short_term_messages(user_id, session_id)
    summaries = load_latest_summaries(user_id, session_id)
    episodes = retrieve_episodes(user_id, user_message)
    prior_messages = short_term[:-1] if short_term and short_term[-1]["role"] == "user" else short_term
    prompt = assemble_prompt(user_message, prior_messages, summaries, episodes)
    result = model_client.complete(prompt)
    save_message(user_id, session_id, "assistant", result.text)
    extract_episodes(user_id, session_id, user_message)
    maybe_summarize(user_id, session_id, model_client)
    system_text = prompt[0]["content"]
    summary_text = "\n".join(
        item["text"]
        for item in (summaries.get("user"), summaries.get("session"))
        if item
    )
    short_term_text = "\n".join(
        item["content"] for item in prior_messages
    )
    episodic_text = "\n".join(item["fact"] for item in episodes)
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    cost_record = {
        "timestamp": now_utc().isoformat(),
        "user_id": user_id,
        "session_id": session_id,
        "prompt_tokens": result.input_tokens,
        "completion_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "component_token_estimates": {
            "system_primer": estimate_tokens(SYSTEM_PRIMER),
            "file_memory": estimate_tokens(file_memory_context()),
            "long_term_summary": estimate_tokens(summary_text),
            "short_term_window": estimate_tokens(short_term_text),
            "episodic_facts": estimate_tokens(episodic_text),
        },
        "latency_ms": latency_ms,
        "config": memory_config(),
    }
    log_chat_cost(cost_record)
    return {
        "reply": result.text,
        "file_memory_auto_compaction": auto_compaction,
        "used": {
            "short_term_message_count": len(short_term),
            "short_term_messages": [
                {"role": item["role"], "content": item["content"]} for item in short_term
            ],
            "long_term_summary": public_summary(
                summaries.get("session") or summaries.get("user")
            ),
            "episodic_facts": [
                {"fact": item["fact"], "importance": item.get("importance"), "similarity": item["similarity"]}
                for item in episodes
            ],
        },
        "usage": {
            "prompt_tokens": result.input_tokens,
            "completion_tokens": result.output_tokens,
            "total_tokens": result.total_tokens,
            "latency_ms": latency_ms,
            "component_token_estimates": cost_record["component_token_estimates"],
            "config": cost_record["config"],
        },
    }


def public_document(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    if "_id" in result:
        result["_id"] = str(result["_id"])
    return result


def public_episode(document: dict[str, Any]) -> dict[str, Any]:
    result = public_document(document)
    result.pop("embedding", None)
    return result


def get_memory(user_id: str) -> dict[str, Any]:
    messages = list(
        get_messages_collection()
        .find({"user_id": user_id})
        .sort("created_at", -1)
        .limit(16)
    )
    episodes = list(
        get_episodes_collection()
        .find({"user_id": user_id})
        .sort("created_at", -1)
        .limit(20)
    )
    summary_collection = get_summaries_collection()
    summaries = {
        "session": summary_collection.find_one(
            {"user_id": user_id, "scope": "session"},
            sort=[("created_at", -1)],
        ),
        "user": summary_collection.find_one(
            {"user_id": user_id, "scope": "user", "session_id": None},
            sort=[("created_at", -1)],
        ),
    }
    return {
        "messages": [public_document(item) for item in reversed(messages)],
        "latest_session_summary": public_summary(summaries["session"]),
        "latest_lifetime_summary": public_summary(summaries["user"]),
        "episodes": [public_episode(item) for item in episodes],
    }


def get_aggregate(user_id: str) -> dict[str, Any]:
    grouped = get_messages_collection().aggregate([
        {"$match": {"user_id": user_id}},
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$created_at",
                        "timezone": "UTC",
                    }
                },
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"_id": 1}},
    ])
    summaries = list(
        get_summaries_collection()
        .find({"user_id": user_id})
        .sort("created_at", -1)
        .limit(5)
    )
    return {
        "daily_message_counts": [
            {"date": row["_id"], "count": row["count"]}
            for row in grouped
        ],
        "recent_summaries": [public_document(item) for item in summaries],
    }
