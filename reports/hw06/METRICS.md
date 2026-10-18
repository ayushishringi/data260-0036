# HW6 Part 3 — Memory Cost Metrics

All experiments used the local Ollama `qwen3:4b` model, five fixed probes from
`memory_probes.yaml`, and a 30-message conversation in a fresh session for each
setting. Prompt tokens and completion tokens are taken from the raw JSONL logs.
Probe quality is the mean of five rubric scores from 1 to 5.

## Comparison

| Setting | Mean prompt tokens/turn | Mean latency (ms) | Probe quality (1–5) | Input tokens/30 turns | Output tokens/30 turns |
|---|---:|---:|---:|---:|---:|
| `SHORT_TERM_N=4`, window | 2,483.53 | 47,488.25 | 3.4 | 74,506 | 51,694 |
| `SHORT_TERM_N=12`, window | 3,250.87 | 40,400.42 | 3.0 | 97,526 | 49,983 |
| `SHORT_TERM_N=30`, window | 3,134.20 | 42,096.02 | 3.4 | 94,026 | 48,039 |
| `SHORT_TERM_N=4`, summary compression | 888.50 | 27,374.00 | 2.2 | 26,655 | 38,804 |

## Policy comparison

Compared with the `SHORT_TERM_N=4` window baseline, summary compression reduced
mean prompt tokens per turn by **64.3%** and mean latency by **42.4%**. Probe
quality decreased from **3.4 to 2.2**, a change of **-1.2 points**. This shows
the trade-off: compression lowers context cost but can remove information needed
for some answers.

## Estimated cost for 10,000 conversations

The estimate uses the required prices: `$1` per million input tokens and `$5`
per million output tokens.

| Setting | Estimated input cost | Estimated output cost | Estimated total cost |
|---|---:|---:|---:|
| `N=4`, window | $745.06 | $2,584.70 | **$3,329.76** |
| `N=12`, window | $975.26 | $2,499.15 | **$3,474.41** |
| `N=30`, window | $940.26 | $2,401.95 | **$3,342.21** |
| `N=4`, summary compression | $266.55 | $1,940.20 | **$2,206.75** |

## Best and worst settings

The best setting for cost is **summary compression**, with an estimated total
cost of `$2,206.75` for 10,000 conversations and the lowest prompt-token use.
Its lower probe score means it is best only when cost and latency are prioritized.

The best quality settings were the `N=4` and `N=30` window runs, both scoring
`3.4`. The worst quality setting was summary compression at `2.2`. The worst
cost setting was `N=12` at `$3,474.41`. The probe scores are rubric-based
heuristics, so they measure the fixed probe set rather than general model quality.

## Reproducibility

The detailed per-request records are in `reports/hw06/raw/chat_costs.jsonl`.
The latest machine-readable benchmark output is in
`reports/hw06/raw/memory_cost_comparison.json`.
