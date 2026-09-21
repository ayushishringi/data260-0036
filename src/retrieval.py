from pathlib import Path

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

    token_index = VectorStoreIndex(
        token_nodes,
        embed_model=embed_model,
    )

    semantic_parser = SemanticSplitterNodeParser(
        buffer_size=1,
        breakpoint_percentile_threshold=95,
        embed_model=embed_model,
    )

    semantic_nodes = semantic_parser.get_nodes_from_documents(documents)

    semantic_index = VectorStoreIndex(
        semantic_nodes,
        embed_model=embed_model,
    )

    window_parser = SentenceWindowNodeParser.from_defaults(
        window_size=3,
        window_metadata_key="window",
        original_text_metadata_key="original_text",
        include_prev_next_rel=True,
    )

    window_nodes = window_parser.get_nodes_from_documents(documents)

    window_index = VectorStoreIndex(
        window_nodes,
        embed_model=embed_model,
    )

    return {
        "token": {
            "index": token_index,
            "nodes": token_nodes,
        },
        "semantic": {
            "index": semantic_index,
            "nodes": semantic_nodes,
        },
        "sentence_window": {
            "index": window_index,
            "nodes": window_nodes,
        },
    }


def query_indexes(indexes, question: str, top_k: int = 3) -> dict:
    results = {}

    for name, pipeline in indexes.items():
        retriever = pipeline["index"].as_retriever(
            similarity_top_k=top_k
        )

        source_nodes = retriever.retrieve(question)

        results[name] = {
            "answer": (
                "Retrieval-only mode: source chunks were retrieved "
                "without using an external LLM."
            ),
            "source_nodes": [
                {
                    "score": node.score,
                    "text": node.node.get_content()[:500],
                }
                for node in source_nodes
            ],
        }

    return results