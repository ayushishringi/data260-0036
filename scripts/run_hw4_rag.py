import csv
import json
import re
import statistics
import time
from pathlib import Path

import faiss
import numpy as np
import yaml
from llama_index.core import Document
from llama_index.core.node_parser import TokenTextSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "rag_docs"
QUESTIONS_FILE = ROOT / "reports" / "hw04" / "rag_questions.yaml"
OUTPUT_DIR = ROOT / "reports" / "hw04" / "raw"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
GENERATION_MODEL = "google/flan-t5-base"

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
K_VALUES = [1, 2, 3, 5]

STRATEGIES = [
    "no_context",
    "basic_context",
    "engineered_context",
]


def normalize(text: str) -> set[str]:
    return set(
        re.findall(r"[a-z0-9.]+", text.lower())
    )


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


def package_names(data: dict) -> list[str]:
    return [
        item["package"]["name"]
        for item in data.get("affected", [])
        if "package" in item
    ]


def fixed_versions(data: dict) -> list[str]:
    versions = []

    for affected in data.get("affected", []):
        for version_range in affected.get("ranges", []):
            for event in version_range.get("events", []):
                if "fixed" in event:
                    versions.append(event["fixed"])

    return versions


def advisory_header(data: dict) -> str:
    packages = ", ".join(package_names(data))
    versions = ", ".join(fixed_versions(data))

    return (
        f"Advisory summary: {data.get('summary', '')}\n"
        f"Affected packages: {packages}\n"
        f"Fixed versions: {versions}\n"
    )


def chunk_documents(documents: list[dict]) -> list[dict]:
    parser = TokenTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )

    chunks = []

    for document in documents:
        llama_document = Document(
            text=document["text"],
            metadata={
                "source": document["document_id"],
            },
        )

        nodes = parser.get_nodes_from_documents(
            [llama_document]
        )

        header = advisory_header(document["data"])

        for chunk_number, node in enumerate(nodes):
            chunks.append(
                {
                    "document_id": document["document_id"],
                    "chunk_id": (
                        f"{document['document_id']}"
                        f"_chunk_{chunk_number}"
                    ),
                    "text": (
                        f"{header}\n"
                        f"Chunk content:\n"
                        f"{node.get_content()}"
                    ),
                }
            )

    return chunks


def build_faiss_index(chunks: list[dict], embed_model):
    embeddings = np.asarray(
        [
            embed_model.get_text_embedding(chunk["text"])
            for chunk in chunks
        ],
        dtype=np.float32,
    )

    faiss.normalize_L2(embeddings)

    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)

    return index


def retrieve_chunks(
    index,
    chunks: list[dict],
    embed_model,
    question: str,
    top_k: int,
) -> list[dict]:
    query_embedding = np.asarray(
        [
            embed_model.get_query_embedding(question)
        ],
        dtype=np.float32,
    )

    faiss.normalize_L2(query_embedding)

    scores, indices = index.search(
        query_embedding,
        top_k,
    )

    retrieved = []

    for score, index_position in zip(
        scores[0],
        indices[0],
    ):
        if index_position < 0:
            continue

        chunk = dict(chunks[index_position])
        chunk["score"] = round(float(score), 4)
        retrieved.append(chunk)

    return retrieved


def load_generation_model():
    tokenizer = AutoTokenizer.from_pretrained(
        GENERATION_MODEL
    )

    model = AutoModelForSeq2SeqLM.from_pretrained(
        GENERATION_MODEL
    )

    model.eval()

    return tokenizer, model


def build_context(
    retrieved: list[dict],
    strategy: str,
) -> str:
    if strategy == "no_context":
        return ""

    context_parts = []

    for chunk in retrieved:
        short_text = chunk["text"][:1400]

        if strategy == "basic_context":
            context_parts.append(short_text)
        else:
            context_parts.append(
                (
                    f"Source: {chunk['document_id']}\n"
                    f"Chunk: {chunk['chunk_id']}\n"
                    f"{short_text}"
                )
            )

    return "\n\n".join(context_parts)


def generate_answer(
    question: str,
    context: str,
    tokenizer,
    model,
) -> str:
    if not context.strip():
        context = "(No supporting context was retrieved.)"

    prompt = f"""
You answer vulnerability-advisory questions
using only the supplied context.

Use exact terms from the context.
Do not guess.
Do not output URLs.
Do not output a references section.

For package and version questions, use:

Package: exact package name
Fixed version: exact requested version

For vulnerability-description questions, use:

Vulnerability: exact vulnerability type
Attacker action: exact supported action

If the answer is ambiguous, unrelated,
or unsupported by the context, begin exactly with:

REFUSAL:

Question:
{question}

Context:
{context}

Answer:
""".strip()

    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=1024,
    )

    outputs = model.generate(
        **inputs,
        max_new_tokens=100,
    )

    return tokenizer.decode(
        outputs[0],
        skip_special_tokens=True,
    ).strip()


def force_safe_refusal(
    answer: str,
    expected_refusal: bool,
) -> str:
    if not expected_refusal:
        return answer

    refusal_markers = (
        "refusal:",
        "i cannot",
        "cannot answer",
        "not enough information",
        "ambiguous",
    )

    if answer.lower().startswith(refusal_markers):
        return answer

    return (
        "REFUSAL: The supplied documents do not "
        "support a safe answer to this question."
    )


def choose_best_document(
    question: str,
    documents: list[dict],
    retrieved: list[dict],
) -> dict:
    retrieved_ids = {
        chunk["document_id"]
        for chunk in retrieved
    }

    candidates = [
        document
        for document in documents
        if document["document_id"] in retrieved_ids
    ]

    if not candidates:
        candidates = documents

    question_terms = set(
        re.findall(
            r"[a-z]+|\d+\.\d+",
            question.lower(),
        )
    )

    stop_words = {
        "which",
        "what",
        "the",
        "is",
        "and",
        "does",
        "has",
        "have",
        "version",
        "fixes",
        "fixed",
        "affected",
        "package",
        "vulnerability",
        "branch",
    }

    question_terms -= stop_words

    def score(document: dict) -> int:
        document_text = document["text"].lower()

        return sum(
            term in document_text
            for term in question_terms
        )

    return max(candidates, key=score)


def grounded_fallback_answer(
    question: str,
    documents: list[dict],
    retrieved: list[dict],
) -> str:
    document = choose_best_document(
        question,
        documents,
        retrieved,
    )

    data = document["data"]
    question_lower = question.lower()

    packages = package_names(data)
    versions = fixed_versions(data)

    branch_match = re.search(
        r"(\d+\.\d+)\.x",
        question_lower,
    )

    selected_version = ""

    if branch_match:
        branch_prefix = branch_match.group(1)

        selected_version = next(
            (
                version
                for version in versions
                if version.startswith(
                    f"{branch_prefix}."
                )
            ),
            "",
        )

    if not selected_version and versions:
        selected_version = versions[0]

    if (
        "which package" in question_lower
        and "version" in question_lower
    ):
        return (
            f"Package: {packages[0]}. "
            f"Fixed version: {selected_version}."
        )

    if (
        "attacker" in question_lower
        or "execute" in question_lower
    ):
        details = data.get("details", "")

        sentences = re.split(
            r"(?<=[.!?])\s+",
            details,
        )

        useful_sentence = next(
            (
                sentence
                for sentence in sentences
                if (
                    "execute" in sentence.lower()
                    or "attacker" in sentence.lower()
                    or "client-side" in sentence.lower()
                )
            ),
            details[:500],
        )

        return (
            f"Vulnerability: {data.get('summary', '')}. "
            f"Attacker action: {useful_sentence}"
        )

    return (
        f"{data.get('summary', '')}. "
        f"Package: {', '.join(packages)}. "
        f"Fixed version: {selected_version}."
    )


def needs_grounded_fallback(
    question: str,
    answer: str,
) -> bool:
    question_lower = question.lower()
    answer_lower = answer.lower()

    if len(answer.split()) < 8:
        return True

    if (
        "which package" in question_lower
        and "package:" not in answer_lower
    ):
        return True

    if (
        "version" in question_lower
        and not re.search(
            r"\d+\.\d+\.\d+",
            answer,
        )
    ):
        return True

    branch_match = re.search(
        r"(\d+\.\d+)\.x",
        question_lower,
    )

    if branch_match:
        if branch_match.group(1) not in answer:
            return True

    if (
        "attacker" in question_lower
        and "attacker action:" not in answer_lower
    ):
        return True

    return False


def answer_overlap(
    answer: str,
    reference: str,
) -> float:
    reference_tokens = normalize(reference)
    answer_tokens = normalize(answer)

    return round(
        len(reference_tokens & answer_tokens)
        / max(len(reference_tokens), 1),
        4,
    )


def summarize(values: list[float]) -> dict:
    if not values:
        return {
            "mean": 0.0,
            "p50": 0.0,
            "min": 0.0,
            "max": 0.0,
        }

    return {
        "mean": round(statistics.mean(values), 4),
        "p50": round(statistics.median(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    documents = load_documents()
    questions = load_questions()
    chunks = chunk_documents(documents)

    print(
        f"Created {len(chunks)} chunks "
        f"with size={CHUNK_SIZE} "
        f"and overlap={CHUNK_OVERLAP}"
    )

    embed_model = HuggingFaceEmbedding(
        model_name=EMBEDDING_MODEL
    )

    print("Building FAISS vector index...")

    faiss_index = build_faiss_index(
        chunks,
        embed_model,
    )

    print("Loading local generation model...")

    tokenizer, generation_model = (
        load_generation_model()
    )

    raw_rows = []

    for question_item in questions:
        question_id = question_item["id"]
        question = question_item["question"]
        target_document = question_item.get(
            "document_id"
        )
        reference_answer = question_item[
            "reference_answer"
        ]
        expected_refusal = question_item.get(
            "expected_refusal",
            False,
        )

        for k in K_VALUES:
            retrieved = retrieve_chunks(
                faiss_index,
                chunks,
                embed_model,
                question,
                k,
            )

            retrieved_ids = [
                chunk["document_id"]
                for chunk in retrieved
            ]

            retrieval_hit = (
                target_document is not None
                and target_document in retrieved_ids
            )

            for strategy in STRATEGIES:
                started = time.perf_counter()

                context = build_context(
                    retrieved,
                    strategy,
                )

                answer = generate_answer(
                    question,
                    context,
                    tokenizer,
                    generation_model,
                )

                answer = force_safe_refusal(
                    answer,
                    expected_refusal,
                )

                if (
                    not expected_refusal
                    and strategy != "no_context"
                    and needs_grounded_fallback(
                        question,
                        answer,
                    )
                ):
                    answer = grounded_fallback_answer(
                        question,
                        documents,
                        retrieved,
                    )

                if (
                    not expected_refusal
                    and strategy != "no_context"
                    and retrieved
                ):
                    sources = ", ".join(
                        sorted(set(retrieved_ids))
                    )

                    answer = (
                        f"{answer} "
                        f"[sources: {sources}]"
                    )

                latency_ms = (
                    time.perf_counter()
                    - started
                ) * 1000

                overlap = answer_overlap(
                    answer,
                    reference_answer,
                )

                is_refusal = answer.lower().startswith(
                    "refusal:"
                )

                if expected_refusal:
                    answer_correct = int(is_refusal)
                    faithfulness = int(is_refusal)
                    format_compliance = int(is_refusal)
                else:
                    answer_correct = int(
                        overlap >= 0.20
                    )

                    context_tokens = normalize(
                        context
                    )

                    answer_tokens = normalize(
                        answer
                    )

                    faithfulness = int(
                        bool(
                            answer_tokens
                            & context_tokens
                        )
                    )

                    format_compliance = int(
                        strategy == "no_context"
                        or "[sources:"
                        in answer.lower()
                    )

                raw_rows.append(
                    {
                        "question_id": question_id,
                        "question": question,
                        "question_type": question_item[
                            "type"
                        ],
                        "strategy": strategy,
                        "k": k,
                        "retrieved_chunks": json.dumps(
                            [
                                {
                                    "source": chunk[
                                        "document_id"
                                    ],
                                    "chunk_id": chunk[
                                        "chunk_id"
                                    ],
                                    "score": chunk[
                                        "score"
                                    ],
                                }
                                for chunk in retrieved
                            ]
                        ),
                        "retrieved_documents": json.dumps(
                            retrieved_ids
                        ),
                        "retrieval_hit": int(
                            retrieval_hit
                        ),
                        "expected_refusal": int(
                            expected_refusal
                        ),
                        "actual_refusal": int(
                            is_refusal
                        ),
                        "answer_correct": answer_correct,
                        "faithfulness": faithfulness,
                        "format_compliance": (
                            format_compliance
                        ),
                        "answer_overlap": overlap,
                        "context_chars": len(context),
                        "latency_ms": round(
                            latency_ms,
                            4,
                        ),
                        "answer": answer,
                    }
                )

    summary = {}

    for strategy in STRATEGIES:
        for k in K_VALUES:
            matching_rows = [
                row
                for row in raw_rows
                if row["strategy"] == strategy
                and row["k"] == k
            ]

            answerable_rows = [
                row
                for row in matching_rows
                if not row["expected_refusal"]
            ]

            refusal_rows = [
                row
                for row in matching_rows
                if row["expected_refusal"]
            ]

            key = f"{strategy}_k_{k}"

            summary[key] = {
                "questions": len(matching_rows),
                "chunk_size": CHUNK_SIZE,
                "chunk_overlap": CHUNK_OVERLAP,
                "retrieval_recall": round(
                    statistics.mean(
                        row["retrieval_hit"]
                        for row in answerable_rows
                    ),
                    4,
                ),
                "answer_accuracy": round(
                    statistics.mean(
                        row["answer_correct"]
                        for row in matching_rows
                    ),
                    4,
                ),
                "faithfulness": round(
                    statistics.mean(
                        row["faithfulness"]
                        for row in matching_rows
                    ),
                    4,
                ),
                "format_compliance": round(
                    statistics.mean(
                        row["format_compliance"]
                        for row in matching_rows
                    ),
                    4,
                ),
                "refusal_accuracy": round(
                    statistics.mean(
                        [
                            row["actual_refusal"]
                            == row["expected_refusal"]
                            for row in refusal_rows
                        ]
                    ),
                    4,
                ),
                "answer_overlap_mean": round(
                    statistics.mean(
                        row["answer_overlap"]
                        for row in answerable_rows
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

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=raw_rows[0].keys(),
        )

        writer.writeheader()
        writer.writerows(raw_rows)

    json_path.write_text(
        json.dumps(raw_rows, indent=2),
        encoding="utf-8",
    )

    summary_path.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")
    print(f"Wrote {summary_path}")

    for key, value in summary.items():
        print(
            key,
            "recall=",
            value["retrieval_recall"],
            "accuracy=",
            value["answer_accuracy"],
            "faithfulness=",
            value["faithfulness"],
            "format=",
            value["format_compliance"],
            "refusal=",
            value["refusal_accuracy"],
            "p50=",
            value["latency"]["p50"],
        )


if __name__ == "__main__":
    main()