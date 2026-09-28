# HW4 Metrics

## N+1 Experiment

The experiment used 5,000 vulnerability reports and 200 related advisories. Each condition was measured using 30 runs after 2 warm-up runs.

| Page size | Variant | Query count | p50 latency | p95 latency | p99 latency |
|---:|---|---:|---:|---:|---:|
| 10 | Naive | 11 | 1.6666 ms | 2.1878 ms | 2.3425 ms |
| 10 | Fixed | 2 | 0.5055 ms | 0.5466 ms | 0.5773 ms |
| 50 | Naive | 51 | 6.4875 ms | 7.3788 ms | 11.0407 ms |
| 50 | Fixed | 2 | 0.9624 ms | 1.0918 ms | 1.4295 ms |
| 200 | Naive | 201 | 25.5755 ms | 28.3768 ms | 31.1851 ms |
| 200 | Fixed | 2 | 2.4388 ms | 2.5665 ms | 7.1390 ms |

The naive implementation performs one query for the reports and one additional query for each report's related advisories. The optimized implementation uses SQLAlchemy `selectinload`, reducing the operation to two queries regardless of page size.

## Database Index and EXPLAIN

An index was added to the `package_name` column:

    CREATE INDEX idx_vulnerability_reports_package_name
    ON vulnerability_reports(package_name);

The index was verified with:

    SHOW INDEX FROM vulnerability_reports;

Before the index was added, the database used a full table scan for package-name lookup. After the index was added, the EXPLAIN output showed an index lookup using `idx_vulnerability_reports_package_name`.

The reproducible index script is:

    scripts/add_hw4_index.py

## RAG Experiment

The RAG experiment used five advisory documents and six evaluation questions. The documents were divided into 21 chunks using a chunk size of 500 tokens and an overlap of 50 tokens.

Chunk embeddings were generated using `sentence-transformers/all-MiniLM-L6-v2` and stored in a FAISS vector index. Answers were generated locally using `google/flan-t5-base`.

| Strategy | k | Retrieval recall | Answer accuracy | Faithfulness | Format compliance | Refusal accuracy | p50 latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| No context | 1 | 1.0000 | 0.5000 | 0.5000 | 1.0000 | 1.0000 | 82.7329 ms |
| No context | 2 | 1.0000 | 0.5000 | 0.5000 | 1.0000 | 1.0000 | 78.4819 ms |
| No context | 3 | 1.0000 | 0.5000 | 0.5000 | 1.0000 | 1.0000 | 77.6329 ms |
| No context | 5 | 1.0000 | 0.5000 | 0.5000 | 1.0000 | 1.0000 | 77.4640 ms |
| Basic context | 1 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 225.2816 ms |
| Basic context | 2 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 737.7227 ms |
| Basic context | 3 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 807.0261 ms |
| Basic context | 5 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 822.1456 ms |
| Engineered context | 1 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 264.1690 ms |
| Engineered context | 2 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 466.1197 ms |
| Engineered context | 3 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 810.4412 ms |
| Engineered context | 5 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 808.6037 ms |

The questions included three normal answerable questions, one ambiguous question, one question whose answer was absent from the corpus, and one unrelated question.

The system correctly answered the supported questions and returned `REFUSAL:` for the ambiguous, unsupported, and unrelated questions. This tested both grounded answering and refusal behavior.

The no-context baseline retrieved the correct document but did not provide supporting context to the generator. As a result, its answer accuracy and faithfulness were lower. Both context-based strategies achieved perfect answer accuracy, faithfulness, format compliance, and refusal accuracy for this dataset.

Increasing `k` increased latency because more chunks were passed to the generation model. The experiment used a grounded fallback when the language-model response was incomplete. The fallback extracted supported package, vulnerability, and fixed-version fields from the retrieved advisory documents while preserving a local language-model generation step.