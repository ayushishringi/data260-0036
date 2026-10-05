# HW5 Metrics

Configuration: SID4 `0036`, PORT_BASE `8036`, PREFIX `s0036`, SEED `36`, VERIFY_SEED `260036`, DOMAIN_ID `4`.

| Injected failure rate | Success rate | Mean latency (ms) | p99 latency (ms) |
|---:|---:|---:|---:|
| 0% | 100% | 0.0005 | 0.0018 |
| 20% | 100% | 3.5059 | 37.5471 |
| 50% | 92% | 10.9042 | 37.6196 |

The retry policy uses three attempts, a five-second operation timeout, and bounded exponential backoff. This is appropriate for interactive calls when transient failures are uncommon; batch processing can use more attempts and a larger capped backoff because throughput is more important than immediate response time.

Agent scenario summaries are recorded in `raw/agent_runs.jsonl`. The offline suite uses `MockModel`; live Ollama scenarios use the configured `qwen3:4b` model when Ollama is available.
