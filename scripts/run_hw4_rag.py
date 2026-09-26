import csv
import json
import re
import statistics
import time
from pathlib import Path

import yaml
from llama_index.embeddings.huggingface import HuggingFaceEmbedding


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "rag_docs"
QUESTIONS_FILE = ROOT / "reports" / "hw04" / "rag_questions.yaml"
OUTPUT_DIR = ROOT / "reports" / "hw04" / "raw"

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
K_VALUES = [1, 2, 3, 5]
STRATEGIES = ["no_context", "basic_context", "engineered_context"]


def normalize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9.]+", text.lower())
    return set(words)


def load_documents() -> list[dict]:
    documents = []

    for path in sorted(DOCS_DIR.glob("doc_*.txt")):
        text = path.read_text(encoding="utf-8")
        json_start = text.index("{")
        data = json.loads(text[json_start:])

        documents.append(
            {
                "document_id": path.stem,
                "text": text,
                "data": data,
            }
        )

    return documents


def load_questions() -> list[dict]:
    return yaml.safe_load(
        QUESTIONS_FILE.read_text(encoding="utf-8")
    )


def fixed_versions(data: dict) -> list[str]:
    versions = []

    for affected in data.get("affected", []):
        for version_range in affected.get("ranges", []):
            for event in version_range.get("events", []):
                if "fixed" in event:
                    versions.append(event["fixed"])

    return versions


def package_names(data: dict) -> list[str]:
    return [
        item["package"]["name"]
        for item in data.get("affected", [])
        if "package" in item
    ]


def extractive_answer(data: dict) -> str:
    packages = ", ".join(package_names(data))
    fixes = ", ".join(fixed_versions(data))
    summary = data.get("summary", "")
    details = data.get("details", "")

    return (
        f"{summary} "
        f"Affected package: {packages}. "
        f"Fixed versions: {fixes}. "
        f"Details: {details[:500]}"
    )


def engineered_context(data: dict) -> str:
    return "\n".join(
        [
            f"Summary: {data.get('summary', '')}",
            f"Package: {', '.join(package_names(data))}",
            f"Fixed versions: {', '.join(fixed_versions(data))}",
            f"Details: {data.get('details', '')[:500]}",
        ]
    )


def cosine_similarity(left, right) -> float:
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5

    if left_norm == 0 or right_norm == 0:
        return 0.0

    dot_product = sum(a * b for a, b in zip(left, right))

    return dot_product / (left_norm * right_norm)


def summarize(values: list[float]) -> dict:
    return {
        "mean": round(statistics.mean(values), 4),
        "p50": round(
            statistics.median(values),
            4,
        ),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    documents = load_documents()
    questions = load_questions()

    embed_model = HuggingFaceEmbedding(
        model_name=MODEL_NAME
    )

    document_embeddings = []

    for document in documents:
        embedding = embed_model.get_text_embedding(
            document["text"]
        )
        document_embeddings.append(embedding)

    raw_rows = []
    summary = {}

    for question_item in questions:
        question_id = question_item["id"]
        question = question_item["question"]
        target_document = question_item["document_id"]
        reference_answer = question_item["reference_answer"]

        query_embedding = embed_model.get_query_embedding(
            question
        )

        scored_documents = []

        for document, embedding in zip(
            documents,
            document_embeddings,
        ):
            score = cosine_similarity(
                query_embedding,
                embedding,
            )

            scored_documents.append(
                {
                    "document": document,
                    "score": score,
                }
            )

        scored_documents.sort(
            key=lambda item: item["score"],
            reverse=True,
        )

        for k in K_VALUES:
            retrieved = scored_documents[:k]
            retrieved_ids = [
                item["document"]["document_id"]
                for item in retrieved
            ]

            retrieval_hit = int(
                target_document in retrieved_ids
            )

            for strategy in STRATEGIES:
                started = time.perf_counter()

                if strategy == "no_context":
                    answer = (
                        "I cannot answer because no context "
                        "was provided."
                    )
                    context_chars = 0

                elif strategy == "basic_context":
                    context = "\n\n".join(
                        item["document"]["text"]
                        for item in retrieved
                    )
                    answer = extractive_answer(
                        retrieved[0]["document"]["data"]
                    )
                    context_chars = len(context)

                else:
                    context = "\n\n".join(
                        engineered_context(
                            item["document"]["data"]
                        )
                        for item in retrieved
                    )
                    answer = extractive_answer(
                        retrieved[0]["document"]["data"]
                    )
                    context_chars = len(context)

                latency_ms = (
                    time.perf_counter() - started
                ) * 1000

                reference_tokens = normalize(
                    reference_answer
                )
                answer_tokens = normalize(answer)

                overlap = len(
                    reference_tokens & answer_tokens
                ) / max(len(reference_tokens), 1)

                raw_rows.append(
                    {
                        "question_id": question_id,
                        "strategy": strategy,
                        "k": k,
                        "retrieved_documents": retrieved_ids,
                        "retrieval_hit": retrieval_hit,
                        "answer_overlap": round(
                            overlap,
                            4,
                        ),
                        "context_chars": context_chars,
                        "latency_ms": round(
                            latency_ms,
                            4,
                        ),
                        "answer": answer,
                    }
                )

    for strategy in STRATEGIES:
        for k in K_VALUES:
            matching_rows = [
                row
                for row in raw_rows
                if row["strategy"] == strategy
                and row["k"] == k
            ]

            key = f"{strategy}_k_{k}"

            summary[key] = {
                "questions": len(matching_rows),
                "retrieval_recall": round(
                    statistics.mean(
                        row["retrieval_hit"]
                        for row in matching_rows
                    ),
                    4,
                ),
                "answer_overlap_mean": round(
                    statistics.mean(
                        row["answer_overlap"]
                        for row in matching_rows
                    ),
                    4,
                ),
                "latency": summarize(
                    [
                        row["latency_ms"]
                        for row in matching_rows
                    ]
                ),
            }

    csv_path = OUTPUT_DIR / "rag_results.csv"
    json_path = OUTPUT_DIR / "rag_results.json"
    summary_path = OUTPUT_DIR / "rag_summary.json"

    with csv_path.open("w", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=raw_rows[0].keys(),
        )
        writer.writeheader()
        writer.writerows(raw_rows)

    json_path.write_text(
        json.dumps(raw_rows, indent=2)
    )

    summary_path.write_text(
        json.dumps(summary, indent=2)
    )

    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")
    print(f"Wrote {summary_path}")

    for key, value in summary.items():
        print(
            key,
            "recall=",
            value["retrieval_recall"],
            "overlap=",
            value["answer_overlap_mean"],
            "p50=",
            value["latency"]["p50"],
        )


if __name__ == "__main__":
    main()