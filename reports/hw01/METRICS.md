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
Raw results: `reports/hw01/raw/nondeterminism_40_runs.json` and `nondeterminism_40_runs.csv`

| Metric | Temp 0.0 | Temp 0.7 |
| --- | --- | --- |
| Distinct tag sets | 1 | 18 |
| Tags in all 20 runs | grpc-security; network-using-privilege-escalation; protobuf-vulnerability | *(none)* |
| Tags in exactly 1 run | *(none)* | gRPC; grpc; grpc-security-vulnerabilities; network reflection; network reflection leaks; network vulnerability; network-exposure; network-isolation; network-privilege; network-privilege-escalation; network-reflect:leak; network-reflectabke-leaks; network-reflective-attack; network-reflective-leak; network-reflective-leaks; network-using; network-vulnerability; protobuf; protobuf reflection; protobuf vulnerabilities; protobuf-java; protobuf-java vulnerabilities; protobuf-reflect; protobuf-reflect-uses; protobuf-upgrades; reflection-leaks; security-vulnerability; security_vulnerability |
| Latency p50 / p95 / p99 (ms) | 3716.2 / 3934.1 / 3947.6 | 3269.9 / 4337.7 / 4449.2 |

Two users submitting the identical input at temperature **0.7** could receive 18 different tag combinations across 20 runs. At temperature **0.0**, all 20 runs produced the same tag set.

**Acceptable variation:** suggested related-topic tags on an advisory page.  
**Unacceptable variation:** using generated tags as a vulnerability-severity or ticket-routing decision because identical reports could be classified differently.

## Part 4 — token accounting

After turn 3 `/stats`:
- turn_count: 3
- cumulative_input_tokens: 476
- cumulative_output_tokens: 9070
- cumulative_total_tokens: 9546
- serialized_conversation_history_length: 1272

After turn 5 `/stats`:
- turn_count: 5
- cumulative_input_tokens: 1059
- cumulative_output_tokens: 13319
- cumulative_total_tokens: 14378
- serialized_conversation_history_length: 1917

Exit totals: input 1059, output 13319, turns 5.