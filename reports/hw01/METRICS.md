# METRICS.md — HW1

## Configuration

| Value | Result |
| --- | --- |
| SID4 | 0036 |
| PORT_BASE | 8036 |
| PREFIX | s0036 |
| SEED | 0036 |
| VERIFY_SEED | 260036 |
| DOMAIN_ID | 4 |

## Part 3 — non-determinism

Fixed input: `reports/hw01/cases/nondeterminism_input.json`  
Model: `qwen3:4b`  
Raw: `reports/hw01/raw/nondeterminism_40_runs.json`, `nondeterminism_40_runs.csv`

| Metric | Temp 0.0 | Temp 0.7 |
| --- | --- | --- |
| Distinct tag sets | 1 | 15 |
| Tags in all 20 runs | grpc-security; protobuf-vulnerability; network-using-privilege-escalation | *(none)* |
| Tags in exactly 1 run | *(none)* | grpc; network security; network-configuration; network-exposure; network-reflect:leak; network-reflective-leaks; network-vulnerability; protobuf; protobuf vulnerabilities; protobuf-java vulnerabilities; protobuf-using; protobuf-versions; reflection attacks; reflection-leak; reflection-leaks; security vulnerability |
| Latency p50 / p95 / p99 (ms) | 3545.1 / 3689.3 / 3766.0 | 3553.2 / 4034.2 / 4079.0 |

Two users sending that same protobuf/gRPC report at temperature **0.7** could get 15 different tag trios (no tag appeared in all 20 runs). At **0.0** they would get the same trio every time.

**Acceptable variation:** a “related topics” chip cloud on a public advisory page. **Unacceptable variation:** using the tags as the CVE severity or ticket routing key, because `network-using-privilege-escalation` vs `reflection-leak` would send the same bug to different queues.

## Part 4 — token accounting

From `python3 hw1_client.py` (scripted 5 turns; `/stats` does not append to history).

After turn 3 `/stats`:

- turn_count: 3
- cumulative_input_tokens: 5084
- cumulative_output_tokens: 5869
- cumulative_total_tokens: 10953
- serialized_conversation_history_length: 29464

After turn 5 `/stats`:

- turn_count: 5
- cumulative_input_tokens: 10313
- cumulative_output_tokens: 7187
- cumulative_total_tokens: 17500
- serialized_conversation_history_length: 36187

Exit totals: input 10313, output 7187, turns 5.

Qwen3 still emits an internal `<think>` trace; `model_client.py` strips it before display so the visible reply can be scored against `AGENT.md`.
