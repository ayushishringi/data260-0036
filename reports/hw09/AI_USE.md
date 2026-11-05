# AI Use — HW9

1. What I used AI for and what I did myself. I used an AI coding assistant to help write the Redis view counter, the semantic cache and its query handler, the stale-answer invalidation, the threshold sweep and cost-model scripts, and the Answering/Evaluator agents with the lesson store. I wrote the 40 labeled cases in cache_cases.yaml before the sweep. I ran Redis, Kafka, the agents and every experiment myself, took the screenshots, checked the results against the assignment and wrote the report.

2. One AI output that was wrong. The first version of the cache ran the SentenceTransformers embedding on the Mac GPU (the default device). Cache hits that came right after an agent run took about 150–235 ms instead of a few milliseconds, which made the cached latency look much worse than the cache really is.

3. How I found it. The handler records a timestamp before and after each step. In the Part 2 output, embed_ms was ~200 ms on those hits but ~6 ms on others, while the vector search was ~2 ms every time. The slow embeddings always followed a pipeline run, when Ollama was using the same GPU.

4. What I changed. The embedding model now runs on the CPU by default (HW9_EMBED_DEVICE=cpu), where one query takes about 3 ms whatever the LLM is doing. I reran the Part 2 demo, and the sweep was run with this setting from the start.
