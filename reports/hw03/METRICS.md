# HW3 Retrieval Metrics

## Configuration

- Domain ID: 4
- Domain: Open-source package vulnerabilities
- Corpus: `corpus/github_reviewed_advisories_snapshot.txt`
- Embedding model: `sentence-transformers/all-MiniLM-L6-v2`
- Questions evaluated: 5
- Retrieval depth: k = 3
- Retrieval mode: Retrieval-only; no external LLM was used

## Retrieval Quality Comparison

| Technique | Chunks | Average chunk length | Top-1 cosine | Mean@3 cosine | Recall@3 | Mean retrieval latency (ms) |
|---|---:|---:|---:|---:|---:|---:|
| Token | 1737 | 1091.45 | 0.484747 | 0.427933 | 0.60 | 16.586620 |
| Semantic | 93 | 18464.80 | 0.405813 | 0.333585 | 0.20 | 4.152180 |
| Sentence-window | 1834 | 936.33 | 0.534835 | 0.479562 | 0.40 | 15.155020 |

## Interpretation

Sentence-window chunking produced the strongest cosine-similarity results. It achieved the highest average top-1 cosine score and the highest mean@3 cosine score. Its sentence-level chunks preserved enough local context while remaining focused on individual advisory statements.

Token chunking achieved the highest Recall@3 using the expected source-match check. It produced moderately sized chunks and performed consistently across the five questions.

Semantic chunking was the fastest at retrieval time and produced far fewer chunks. However, its average chunk length was much larger, and its cosine and recall values were lower. Large semantic chunks may contain several unrelated advisory sections, which can reduce retrieval precision for focused questions.

## Conclusion

For this vulnerability-advisory corpus, Sentence-window chunking is the best overall technique based on cosine similarity. Token chunking is a strong alternative when source-match recall is prioritized. Semantic chunking is fastest but less precise for these questions because its chunks are very large.

## Reproducibility

The raw per-query and per-technique results are stored in:

```text
reports/hw03/raw/retrieval_outputs.json