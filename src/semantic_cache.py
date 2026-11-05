"""HW9 Parts 2-3: semantic response cache at the ingress of the HW8 Q&A pipeline.

Each cache entry is a Redis hash s0036:qcache:<uuid> holding the query, its embedding
(all-MiniLM-L6-v2, 384-dim float32), the final answer, and a data-version marker for the
s0036_rel records the answer depends on. A RediSearch vector index (s0036:idx:qcache, cosine
distance) finds the nearest cached query; similarity = 1 - cosine distance.

CachedQA.ask():
  hit  (similarity >= threshold, and the data version still matches) -> stored answer, is_cached=True
  miss -> HW8 agent path (s0036_inbox -> ... -> s0036_final), store the answer, is_cached=False
Invalidation (Part 3.5): "version" re-reads the record(s) behind a hit and treats a changed
data_version as a miss (the stale entry is deleted); "none" returns whatever is cached.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Protocol

import numpy as np
import redis
from redis.commands.search.field import NumericField, TagField, TextField, VectorField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from src import advisory_lookup
from src.kafka_common import PREFIX, log

INDEX_NAME = f"{PREFIX}:idx:qcache"
KEY_PREFIX = f"{PREFIX}:qcache:"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DIM = 384
DEFAULT_THRESHOLD = 0.85


class Embedder:
    """SentenceTransformers model producing unit-length float32 vectors."""

    def __init__(self, model_name: str = EMBED_MODEL) -> None:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")  # the model is already in the local Hugging Face cache
        from sentence_transformers import SentenceTransformer
        # CPU by default: on the Mac GPU the embedding waits behind Ollama (~200 ms instead of ~6 ms).
        self.model = SentenceTransformer(model_name, device=os.getenv("HW9_EMBED_DEVICE", "cpu"))

    def embed(self, text: str) -> np.ndarray:
        """Embedding of one text, normalized so cosine similarity is a dot product."""

        return self.model.encode([text], normalize_embeddings=True)[0].astype(np.float32)


class Answerer(Protocol):
    def ask(self, question: str, timeout: float = 300) -> dict[str, Any]: ...


class SemanticCache:
    """Vector-indexed cache entries in Redis."""

    def __init__(self, redis_client: redis.Redis, index_name: str = INDEX_NAME, key_prefix: str = KEY_PREFIX) -> None:
        self.r = redis_client
        self.index_name = index_name
        self.key_prefix = key_prefix
        self.ensure_index()

    def ensure_index(self) -> None:
        """Create the FLAT (exact) cosine vector index over s0036:qcache:* hashes if it does not exist."""

        try:
            self.r.ft(self.index_name).info()
        except redis.ResponseError:
            self.r.ft(self.index_name).create_index(
                [TextField("query"), TextField("answer"), TagField("data_version"), TagField("record_ids"),
                 NumericField("created_at"),
                 VectorField("embedding", "FLAT", {"TYPE": "FLOAT32", "DIM": DIM, "DISTANCE_METRIC": "COSINE"})],
                definition=IndexDefinition(prefix=[self.key_prefix], index_type=IndexType.HASH))

    def clear(self) -> int:
        """Delete every cache entry (and keep the index)."""

        keys = list(self.r.scan_iter(match=f"{self.key_prefix}*", count=500))
        if keys:
            self.r.delete(*keys)
        return len(keys)

    def size(self) -> int:
        return int(self.r.ft(self.index_name).info()["num_docs"])

    def nearest(self, vector: np.ndarray) -> dict[str, Any] | None:
        """The cached entry closest to the vector, with its cosine similarity."""

        query = (Query("*=>[KNN 1 @embedding $vec AS distance]").sort_by("distance")
                 .return_fields("query", "answer", "data_version", "record_ids", "distance").dialect(2))
        docs = self.r.ft(self.index_name).search(query, query_params={"vec": vector.tobytes()}).docs
        if not docs:
            return None
        doc = docs[0]
        ids = [int(x) for x in doc.record_ids.split(",") if x] if doc.record_ids else []
        return {"key": doc.id, "query": doc.query, "answer": doc.answer, "data_version": doc.data_version,
                "record_ids": ids, "similarity": round(1.0 - float(doc.distance), 4)}

    def store(self, query: str, vector: np.ndarray, answer: str, data_version: str, record_ids: list[int],
              **extra: str) -> str:
        """Save one entry; returns its Redis key."""

        key = f"{self.key_prefix}{uuid.uuid4().hex}"
        self.r.hset(key, mapping={"query": query, "embedding": vector.tobytes(), "answer": answer,
                                  "data_version": data_version, "record_ids": ",".join(map(str, record_ids)),
                                  "created_at": time.time(), **extra})
        return key

    def delete(self, key: str) -> None:
        self.r.delete(key)


def ms(start: float, end: float) -> float:
    return round((end - start) * 1000, 2)


class CachedQA:
    """Query handler: semantic cache first, HW8 agent pipeline on a miss."""

    def __init__(self, cache: SemanticCache, embedder: Embedder, pipeline: Answerer,
                 threshold: float = DEFAULT_THRESHOLD, invalidation: str = "version", store_on_miss: bool = True,
                 component: str = "semantic-cache") -> None:
        if invalidation not in ("version", "none"):
            raise ValueError("invalidation must be 'version' or 'none'")
        self.cache, self.embedder, self.pipeline = cache, embedder, pipeline
        self.threshold, self.invalidation, self.store_on_miss = threshold, invalidation, store_on_miss
        self.component = component

    def ask(self, query: str, threshold: float | None = None) -> dict[str, Any]:
        """Answer one query; the result carries is_cached, similarity and latency_ms."""

        threshold = self.threshold if threshold is None else threshold
        timings: dict[str, float] = {}
        t0 = time.perf_counter()
        vector = self.embedder.embed(query)
        t1 = time.perf_counter()
        timings["embed_ms"] = ms(t0, t1)
        best = self.cache.nearest(vector)
        t2 = time.perf_counter()
        timings["search_ms"] = ms(t1, t2)
        similarity = best["similarity"] if best else None
        result: dict[str, Any] = {"query": query, "threshold": threshold, "similarity": similarity,
                                  "matched_query": best["query"] if best else None}

        stale = False
        if best and similarity >= threshold:
            if self.invalidation == "version":
                current = advisory_lookup.current_version(best["record_ids"])
                timings["version_check_ms"] = ms(t2, time.perf_counter())
                stale = current != best["data_version"]
            if stale:
                self.cache.delete(best["key"])
                log(self.component, "STALE entry invalidated (data_version changed)", similarity=similarity,
                    cached_query=best["query"], stored_version=best["data_version"], current_version=current)
            else:
                latency = ms(t0, time.perf_counter())
                log(self.component, "CACHE HIT", similarity=similarity, threshold=threshold,
                    cached_query=best["query"], latency_ms=latency)
                return {**result, "is_cached": True, "answer": best["answer"], "data_version": best["data_version"],
                        "record_ids": best["record_ids"], "latency_ms": latency, "timings": timings}

        log(self.component, "CACHE MISS", best_similarity=similarity, threshold=threshold, query=query,
            reason="stale" if stale else ("empty cache" if best is None else "below threshold"))
        # The data version is read BEFORE the agents run, so an update during the run makes the entry stale.
        records = advisory_lookup.find_records(query)
        version = advisory_lookup.data_version(records)
        t3 = time.perf_counter()
        final = self.pipeline.ask(query)
        t4 = time.perf_counter()
        timings["pipeline_ms"] = ms(t3, t4)
        answer, status = final.get("answer", ""), final.get("status")
        stored_key = None
        if self.store_on_miss and status == "approved":
            stored_key = self.cache.store(query, vector, answer, version, [r["id"] for r in records],
                                          correlation_id=final.get("correlation_id", ""))
        timings["store_ms"] = ms(t4, time.perf_counter())
        latency = ms(t0, time.perf_counter())
        log(self.component, "ANSWERED by agent pipeline", correlation_id=final.get("correlation_id"),
            status=status, stored=bool(stored_key), latency_ms=latency)
        return {**result, "is_cached": False, "answer": answer, "status": status, "stale_invalidated": stale,
                "correlation_id": final.get("correlation_id"), "data_version": version,
                "record_ids": [r["id"] for r in records], "latency_ms": latency, "timings": timings}
