import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.retrieval import build_indexes, query_indexes


QUESTIONS = [
    "Which packages are affected by prototype pollution vulnerabilities?",
    "What versions of Apache Pulsar are affected by security vulnerabilities?",
    "What are common mitigation steps described in the advisories?",
    "Which vulnerabilities allow remote code execution?",
    "Which advisories mention denial of service?",
]


def main():
    print("Building the three retrieval indexes...")
    indexes = build_indexes()

    all_results = []

    for question in QUESTIONS:
        print(f"\nQuestion: {question}")

        results = query_indexes(
            indexes,
            question,
            top_k=3,
        )

        all_results.append(
            {
                "question": question,
                "results": results,
            }
        )

        for method, data in results.items():
            print(
                f"{method}: "
                f"{len(data['source_nodes'])} source chunks retrieved"
            )

    output_dir = ROOT / "outputs"
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / "hw3_retrieval_outputs.json"

    output_file.write_text(
        json.dumps(all_results, indent=2),
        encoding="utf-8",
    )

    print(f"\nSaved results to: {output_file}")


if __name__ == "__main__":
    main()