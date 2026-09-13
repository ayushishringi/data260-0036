# METRICS.md — DATA-260 HW2

## Configuration

| Value | Result |
| --- | --- |
| SID4 | 0036 |
| PORT_BASE | 8036 |
| PREFIX | s0036 |
| SEED | 0036 |
| VERIFY_SEED | 260036 |
| DOMAIN_ID | 4 |
| Domain | Open-source package vulnerabilities |
| Model | qwen3:4b |
| Hardware | MacBook Pro, Apple M5 Pro, 24 GB RAM |
| Deployment turn ceiling | 10 |

## Schema-validation experiment

Fixed input: `reports/hw02/cases/schema_input.json`

Number of runs: 30

| Outcome | Count |
| --- | ---: |
| Valid first attempt | 30 |
| Valid after 1 retry | 0 |
| Valid after 2+ retries | 0 |
| Hit turn ceiling | 0 |

Completion rate: 100%

Mean latency: 848.42 ms

Raw files:

- `reports/hw02/raw/schema_30_runs.json`
- `reports/hw02/raw/schema_30_runs.csv`
- `reports/hw02/raw/schema_30_runs_metrics.json`

## Turn-ceiling comparison

The same frozen input and model settings were used for both experiments.

| Turn ceiling | Runs | Completed | Completion rate | Mean latency |
| ---: | ---: | ---: | ---: | ---: |
| 2 | 20 | 20 | 100% | 855.11 ms |
| 10 | 20 | 20 | 100% | 840.64 ms |

Both ceilings achieved 100% completion on the fixed input. The deployment ceiling was set to 10 because it had the lower measured mean latency while maintaining the same completion rate.

Raw files:

- `reports/hw02/raw/ceiling_2_20_runs.json`
- `reports/hw02/raw/ceiling_2_20_runs.csv`
- `reports/hw02/raw/ceiling_2_20_runs_metrics.json`
- `reports/hw02/raw/ceiling_10_20_runs.json`
- `reports/hw02/raw/ceiling_10_20_runs.csv`
- `reports/hw02/raw/ceiling_10_20_runs_metrics.json`

## Adversarial experiment

The adversarial input intentionally included conflicting instructions requesting:

- Four tags instead of exactly three
- A summary longer than 25 words
- Instructions to ignore the required schema

Number of runs: 5

Turn ceiling: 2

| Outcome | Count |
| --- | ---: |
| Valid first attempt | 0 |
| Valid after 1 retry | 0 |
| Valid after 2+ retries | 0 |
| Hit turn ceiling | 5 |

Completion rate: 0%

Mean latency: 2069.50 ms

Each run attempted the Planner twice. Pydantic detected invalid output after both attempts, and the graph stopped at the configured ceiling without hanging or looping indefinitely.

The adversarial input caused trouble because it contained prompt-injection-style instructions that conflicted with the required output schema. One possible improvement is to use stricter constrained decoding or a deterministic repair step that trims the output to exactly three valid tags and a 25-word summary before retrying.

Raw files:

- `reports/hw02/cases/adversarial_input.json`
- `reports/hw02/raw/adversarial_5_runs.json`
- `reports/hw02/raw/adversarial_5_runs.csv`
- `reports/hw02/raw/adversarial_5_runs_metrics.json`