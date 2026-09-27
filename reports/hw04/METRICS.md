# HW4 Metrics

## N+1 experiment

The experiment used 5,000 vulnerability reports and 200 related advisories.
Each condition was measured with 30 runs after 2 warm-up runs.

| Page size | Variant | Query count | p50 latency (ms) | p95 latency (ms) | p99 latency (ms) |
|---:|---|---:|---:|---:|---:|
| 10 | Naive | 11 | 1.6666 | 2.1878 | 2.3425 |
| 10 | Fixed | 2 | 0.5055 | 0.5466 | 0.5773 |
| 50 | Naive | 51 | 6.4875 | 7.3788 | 11.0407 |
| 50 | Fixed | 2 | 0.9624 | 1.0918 | 1.4295 |
| 200 | Naive | 201 | 25.5755 | 28.3768 | 31.1851 |
| 200 | Fixed | 2 | 2.4388 | 2.5665 | 7.1390 |

The naive implementation performs one query for the main reports plus
one query per report for related advisories. The fixed implementation
uses SQLAlchemy `selectinload`, reducing the query count to two.

## RAG experiment

The RAG experiment used five advisory documents, six questions, and
k values of 1, 2, 3, and 5.

| Strategy | k | Retrieval recall | Answer overlap |
|---|---:|---:|---:|
| No context | 1 | 0.6667 | 0.0000 |
| No context | 2 | 0.8333 | 0.0000 |
| No context | 3 | 1.0000 | 0.0000 |
| No context | 5 | 1.0000 | 0.0000 |
| Basic context | 1 | 0.6667 | 0.4785 |
| Basic context | 2 | 0.8333 | 0.4785 |
| Basic context | 3 | 1.0000 | 0.4785 |
| Basic context | 5 | 1.0000 | 0.4785 |
| Engineered context | 1 | 0.6667 | 0.4785 |
| Engineered context | 2 | 0.8333 | 0.4785 |
| Engineered context | 3 | 1.0000 | 0.4785 |
| Engineered context | 5 | 1.0000 | 0.4785 |

Increasing k improved retrieval recall. Context-based answers had
higher answer overlap than the no-context baseline. Basic and
engineered context produced the same overlap because the experiment
used a deterministic extractive answer function rather than a
generative language model.