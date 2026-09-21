import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.retrieval import build_indexes, query_indexes


RAW_DIR = ROOT / "reports" / "hw03" / "raw"
OUTPUT_DIR = ROOT / "outputs"


def load_questions() -> list[dict]:
    questions_file = ROOT / "questions.yaml"

    data = yaml.safe_load(
        questions_file.read_text(encoding="utf-8")
    )

    return data["questions"]


def mean_or_zero(values: list[float]) -> float:
    if not values:
        return 0.0

    return round(statistics.mean(values), 6)


def calculate_metrics(all_results: list[dict]) -> dict:
    metrics = {}

    technique_names = [
        "token",
        "semantic",
        "sentence_window",
    ]

    for technique in technique_names:
        technique_rows = [
            item["results"][technique]
            for item in all_results
        ]

        top1_values = []
        mean_at_k_values = []
        latency_values = []
        recall_values = []

        for question_item, row in zip(
            all_results,
            technique_rows,
        ):
            cosine_values = [
                source["cosine_similarity"]
                for source in row["source_nodes"]
            ]

            if cosine_values:
                top1_values.append(max(cosine_values))
                mean_at_k_values.append(
                    statistics.mean(cosine_values)
                )

            latency_values.append(
                row["retrieval_latency_ms"]
            )

            expected_match = question_item.get(
                "expected_source_match",
                "",
            ).lower()

            previews = [
                source["preview"].lower()
                for source in row["source_nodes"]
            ]

            found = any(
                expected_match in preview
                for preview in previews
            )

            recall_values.append(1 if found else 0)

        first_row = technique_rows[0]

        metrics[technique] = {
            "questions_evaluated": len(technique_rows),
            "chunks_produced": first_row["chunk_count"],
            "average_chunk_length": first_row[
                "avg_chunk_length"
            ],
            "top_1_cosine_mean": mean_or_zero(top1_values),
            "mean_at_k_cosine": mean_or_zero(
                mean_at_k_values
            ),
            "recall_at_k": mean_or_zero(recall_values),
            "mean_retrieval_latency_ms": mean_or_zero(
                latency_values
            ),
        }

    return metrics


def main():
    questions = load_questions()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    log_lines = [
        "HW3 retrieval run",
        (
            "timestamp_utc: "
            f"{datetime.now(timezone.utc).isoformat()}"
        ),
        "model: sentence-transformers/all-MiniLM-L6-v2",
        "top_k: 3",
        "",
        "Building the three retrieval indexes...",
    ]

    print(log_lines[-1])

    indexes = build_indexes()
    all_results = []

    for question_item in questions:
        question_id = question_item["id"]
        question_text = question_item["text"]

        print(f"\nQuestion {question_id}: {question_text}")

        results = query_indexes(
            indexes,
            question_text,
            top_k=3,
        )

        result_record = {
            "question_id": question_id,
            "question": question_text,
            "expected_answer": question_item.get(
                "expected_answer",
                "",
            ),
            "expected_source_file": question_item.get(
                "expected_source_file",
                "",
            ),
            "expected_source_match": question_item.get(
                "expected_source_match",
                "",
            ),
            "results": results,
        }

        all_results.append(result_record)

        log_lines.append(
            f"Question {question_id}: {question_text}"
        )

        for technique, data in results.items():
            message = (
                f"{technique}: "
                f"{len(data['source_nodes'])} chunks, "
                f"latency="
                f"{data['retrieval_latency_ms']} ms"
            )

            print(message)
            log_lines.append(message)

    metrics = calculate_metrics(all_results)

    raw_output_file = RAW_DIR / "retrieval_outputs.json"
    raw_output_file.write_text(
        json.dumps(all_results, indent=2),
        encoding="utf-8",
    )

    metrics_file = RAW_DIR / "metrics.json"
    metrics_file.write_text(
        json.dumps(metrics, indent=2),
        encoding="utf-8",
    )

    output_file = OUTPUT_DIR / "hw3_retrieval_outputs.json"
    output_file.write_text(
        json.dumps(all_results, indent=2),
        encoding="utf-8",
    )

    log_lines.extend(
        [
            "",
            "Summary metrics:",
            json.dumps(metrics, indent=2),
            "",
            f"Saved: {raw_output_file}",
            f"Saved: {metrics_file}",
            f"Saved: {output_file}",
        ]
    )

    run_log_file = ROOT / "reports" / "hw03" / "RUN_LOG.txt"
    run_log_file.parent.mkdir(parents=True, exist_ok=True)
    run_log_file.write_text(
        "\n".join(log_lines) + "\n",
        encoding="utf-8",
    )

    print("\nSummary metrics:")
    print(json.dumps(metrics, indent=2))
    print(f"\nSaved: {raw_output_file}")
    print(f"Saved: {metrics_file}")
    print(f"Saved: {output_file}")


if __name__ == "__main__":
    main()