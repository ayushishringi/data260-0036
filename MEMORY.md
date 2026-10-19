# Durable Memory
<!-- consolidated_at: 2026-10-19T01:07:09.072523+00:00 -->
## Facts
- [2026-10-17] course: DATA-260 (seen 3x)
- [2026-10-17] sid4: 0036 (seen 2x)
- [2026-08-25] domain: open-source package vulnerability tracking (DOMAIN_ID 4)
- [2026-10-17] api_framework: FastAPI (seen 3x)
- [2026-09-02] validation: Pydantic v2 models for every request body
- [2026-09-10] python_version: 3.12
- [2026-10-18] hardware: MacBook Pro, Apple M5 Pro, 24 GB (seen 2x)
- [2026-10-16] mongo_database: s0036_doc (seen 2x)
- [2026-10-01] documents_collection: vulnerability_documents
- [2026-10-17] memory_collections: messages, summaries, episodes (seen 2x)
- [2026-10-17] ollama_model: qwen3:4b (seen 2x)
- [2026-10-18] severity_values: critical, high, medium, low (seen 2x)
- [2026-10-18] status_values: open, triaged, resolved, ignored (seen 2x)
- [2026-10-17] episodic_top_k: 3 (seen 2x)
- [2026-10-05] embedding_model: all-MiniLM-L6-v2 with a hash-vector fallback
- [2026-10-18] ollama_num_ctx: 16384 (seen 2x)
- [2026-10-06] ollama_seed: 36
- [2026-10-17] input_price: $1 per million tokens (seen 2x)
- [2026-10-17] output_price: $5 per million tokens (seen 2x)
- [2026-10-17] collaborators: Sbnikitha, supriyaselvanganesan (seen 2x)
- [2026-10-18] submission_tag: hw6 (seen 2x)
- [2026-10-08] report_file: Shringi_HW6.pdf
- [2026-10-09] test_runner: unittest (pytest is not installed in .venv)
- [2026-10-09] lifetime_summary_every: 2 session summaries
- [2026-10-17] The user prefers short, numbered answers in reports. (seen 2x)
- [2026-10-17] Raw experiment output always goes under reports/hw06/raw/. (seen 2x)
- [2026-10-15] short_term_n_default: 12
- [2026-10-15] summarize_every_user_msgs: 5
- [2026-10-16] memory_policy_options: window, compressed_window
- [2026-10-18] port: 8036

## Resolved contradictions
- port: kept "8000" [2026-10-14]; superseded "8036" [2026-09-01]
- ollama_model: kept "qwen3:4b" [2026-10-17]; superseded "llama3.2:3b" [2026-09-05]
- short_term_n_default: kept "12" [2026-10-15]; superseded "8" [2026-10-03]
- summarize_every_user_msgs: kept "5" [2026-10-15]; superseded "3" [2026-10-04]
- port: kept "8036" [2026-10-18]; superseded "8000" [2026-10-14]
