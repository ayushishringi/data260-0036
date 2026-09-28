import time
from pathlib import Path

import numpy as np
from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.node_parser import (
    SemanticSplitterNodeParser,
    SentenceWindowNodeParser,
    TokenTextSplitter,
)
from llama_index.embeddings.huggingface import HuggingFaceEmbedding


ROOT = Path(__file__).resolve().parents[1]
CORPUS_FILE = ROOT / "corpus" / "github_reviewed_advisories_snapshot.txt"

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def load_corpus() -> list[Document]:
    text = CORPUS_FILE.read_text(encoding="utf-8")

    if len(text.encode("utf-8")) < 200_000:
        raise ValueError("Corpus must be at least 200 KB.")

    return [
        Document(
            text=text,
            metadata={
                "source": "GitHub Advisory Database",
                "corpus_file": str(CORPUS_FILE),
            },
        )
    ]


def average_chunk_length(nodes) -> float:
    if not nodes:
        return 0.0

    lengths = [
        len(node.get_content())
        for node in nodes
    ]

    return round(float(np.mean(lengths)), 2)


def create_pipeline(nodes, embed_model):
    return {
        "index": VectorStoreIndex(
            nodes,
            embed_model=embed_model,
        ),
        "nodes": nodes,
        "embed_model": embed_model,
        "chunk_count": len(nodes),
        "avg_chunk_length": average_chunk_length(nodes),
    }


def build_indexes():
    embed_model = HuggingFaceEmbedding(
        model_name=MODEL_NAME
    )

    Settings.embed_model = embed_model

    documents = load_corpus()

    token_parser = TokenTextSplitter(
        chunk_size=512,
        chunk_overlap=50,
    )

    token_nodes = token_parser.get_nodes_from_documents(documents)

    semantic_parser = SemanticSplitterNodeParser(
        buffer_size=1,
        breakpoint_percentile_threshold=95,
        embed_model=embed_model,
    )

    semantic_nodes = semantic_parser.get_nodes_from_documents(documents)

    window_parser = SentenceWindowNodeParser.from_defaults(
        window_size=3,
        window_metadata_key="window",
        original_text_metadata_key="original_text",
        include_prev_next_rel=True,
    )

    window_nodes = window_parser.get_nodes_from_documents(documents)

    return {
        "token": create_pipeline(
            token_nodes,
            embed_model,
        ),
        "semantic": create_pipeline(
            semantic_nodes,
            embed_model,
        ),
        "sentence_window": create_pipeline(
            window_nodes,
            embed_model,
        ),
    }


def cosine_similarity(query_vector, document_vector) -> float:
    query_norm = np.linalg.norm(query_vector)
    document_norm = np.linalg.norm(document_vector)

    if query_norm == 0 or document_norm == 0:
        return 0.0

    return float(
        np.dot(query_vector, document_vector)
        / (query_norm * document_norm)
    )


def query_indexes(indexes, question: str, top_k: int = 3) -> dict:
    results = {}

    for name, pipeline in indexes.items():
        embed_model = pipeline["embed_model"]

        query_embedding = np.asarray(
            embed_model.get_query_embedding(question),
            dtype=np.float32,
        )

        retriever = pipeline["index"].as_retriever(
            similarity_top_k=top_k
        )

        started = time.perf_counter()
        source_nodes = retriever.retrieve(question)
        retrieval_latency_ms = (
            time.perf_counter() - started
        ) * 1000

        retrieved_rows = []
        document_vectors = []

        for rank, node_with_score in enumerate(
            source_nodes,
            start=1,
        ):
            text = node_with_score.node.get_content()

            document_embedding = np.asarray(
                embed_model.get_text_embedding(text),
                dtype=np.float32,
            )

            document_vectors.append(document_embedding)

            retrieved_rows.append(
                {
                    "rank": rank,
                    "store_score": (
                        float(node_with_score.score)
                        if node_with_score.score is not None
                        else None
                    ),
                    "cosine_similarity": round(
                        cosine_similarity(
                            query_embedding,
                            document_embedding,
                        ),
                        6,
                    ),
                    "chunk_length": len(text),
                    "preview": text[:160].replace("\n", " "),
                }
            )

        if document_vectors:
            document_matrix = np.vstack(document_vectors)
            document_shape = list(document_matrix.shape)
        else:
            document_shape = [0, int(query_embedding.shape[0])]

        results[name] = {
            "technique": name,
            "question": question,
            "chunk_count": pipeline["chunk_count"],
            "avg_chunk_length": pipeline["avg_chunk_length"],
            "query_embedding_dimension": int(
                query_embedding.shape[0]
            ),
            "query_embedding_first_8": [
                round(float(value), 8)
                for value in query_embedding[:8]
            ],
            "query_vector_shape": list(query_embedding.shape),
            "document_vectors_shape": document_shape,
            "retrieval_latency_ms": round(
                retrieval_latency_ms,
                4,
            ),
            "source_nodes": retrieved_rows,
        }

    return results