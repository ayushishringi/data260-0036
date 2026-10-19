# HW6 Part 3: Memory Cost Metrics

Model: Ollama `qwen3:4b` (num_ctx 16384, seed 36). Each setting ran in a fresh uvicorn process with `SHORT_TERM_N`/`MEMORY_POLICY` set, in a fresh session, with the same 30-message conversation, followed by the 5 probes in `memory_probes.yaml`. Per-turn means cover the 30 conversation turns. Raw data: `raw/memory_cost_comparison.json`, `raw/per_turn_tokens.csv`, `raw/chat_costs.jsonl`.

## Results

| Setting | Mean prompt tokens/turn | Mean latency (ms) | Probe quality (1-5) |
|---|---:|---:|---:|
| `N=4,window` | 1,869.8 | 41,090 | 5.0 |
| `N=12,window` | 2,527.4 | 60,500 | 5.0 |
| `N=30,window` | 3,372.8 | 59,872 | 5.0 |
| `N=12,compressed_window` | 2,031.5 | 58,012 | 5.0 |

## Probe scores (planted turn → score)

| Setting | probe_1 (t2) | probe_2 (t9) | probe_3 (t17) | probe_4 (t23) | probe_5 (t27) |
|---|---:|---:|---:|---:|---:|
| `N=4,window` | 5 | 5 | 5 | 5 | 5 |
| `N=12,window` | 5 | 5 | 5 | 5 | 5 |
| `N=30,window` | 5 | 5 | 5 | 5 | 5 |
| `N=12,compressed_window` | 5 | 5 | 5 | 5 | 5 |

## Mean estimated tokens per prompt component (conversation turns)

| Setting | system_primer | file_memory | long_term_summary | short_term_window | episodic_facts | messages in window |
|---|---:|---:|---:|---:|---:|---:|
| `N=4,window` | 41 | 912 | 104 | 288 | 44 | 3.9 |
| `N=12,window` | 41 | 912 | 196 | 898 | 44 | 10.8 |
| `N=30,window` | 41 | 912 | 123 | 1,909 | 44 | 22.5 |
| `N=12,compressed_window` | 41 | 912 | 92 | 439 | 44 | 10.8 |

## Compression policy vs. its baseline (both N=12)

`compressed_window` keeps the last N messages but cuts every assistant reply except the latest to 240 characters; user messages stay verbatim, and the session summary and episodic facts carry the rest.

| Metric | `N=12,window` | `N=12,compressed_window` | Change |
|---|---:|---:|---:|
| Mean prompt tokens/turn | 2,527.4 | 2,031.5 | -19.6% |
| Mean short-term window tokens/turn | 898.4 | 439.5 | -51.1% |
| Input tokens / 30-turn conversation | 75,822 | 60,944 | -19.6% |
| Mean latency (ms) | 60,500 | 58,012 | -4.1% |
| Probe quality | 5.0 | 5.0 | +0.0 |

## Estimated cost of 10,000 30-turn conversations

Input $1/M tokens, output $5/M tokens, using the measured input and output tokens of each 30-turn run (probes excluded).

| Setting | Input tokens/conv | Output tokens/conv | Input cost | Output cost | Total cost | $ per probe-quality point |
|---|---:|---:|---:|---:|---:|---:|
| `N=4,window` | 56,095 | 22,201 | $560.95 | $1,110.05 | **$1,671.00** | $334.20 |
| `N=12,window` | 75,822 | 22,386 | $758.22 | $1,119.30 | **$1,877.52** | $375.50 |
| `N=30,window` | 101,183 | 21,421 | $1,011.83 | $1,071.05 | **$2,082.88** | $416.58 |
| `N=12,compressed_window` | 60,944 | 19,864 | $609.44 | $993.20 | **$1,602.64** | $320.53 |

## Best and worst settings

Selection rule: total cost divided by mean probe quality (dollars per quality point), so a setting only counts as best if it is cheap without losing memory quality.

- Best: `N=12,compressed_window`: $1,602.64 for 10,000 conversations at probe quality 5.0.
- Worst: `N=30,window`: $2,082.88 for 10,000 conversations at probe quality 5.0.
- Difference: $480.24.

## Findings

- Window size drives input cost. Mean short-term-window tokens grew from 288 (N=4) to 898 (N=12) to
  1,909 (N=30), and mean prompt tokens from 1,870 to 2,527 to 3,373. N=30 costs about 80% more input per
  conversation than N=4.
- Probe quality was 5.0 in every setting because episodic retrieval returned the planted fact as the
  top match for every probe, including N=4 where all five facts were outside the 4-message window
  (`episodic_facts_used` in `raw/memory_cost_comparison.json`). With episodic memory on, a larger window
  added cost without improving recall on these probes.
- `compressed_window` cut short-term-window tokens by 51% and prompt tokens by 19.6% versus `N=12,window`,
  with no quality change.
- On input tokens alone, `N=4,window` is cheapest (56,095 vs. 60,944). `compressed_window` has the lowest
  total cost because its replies were also shorter (19,864 vs. 22,201 output tokens), and output is priced
  5x. That output difference comes from reply-length variation rather than the policy, so the two settings
  are effectively tied on cost.
- Latency is not a reliable ranking signal here. Summarization runs inside every 5th request (turns 5, 10,
  15, 20, 25, 30 took 50-260 s), and the runs were sequential on one laptop, so later runs were slower
  (N=4 ran first at 41 s mean; the others ran at 58-60 s).

## Limitations

One run per setting with five keyword-scored probes; latency is from one Apple M5 Pro laptop running Ollama locally. Output tokens are priced at 5x input and depend on reply length, which memory does not control directly. Component token counts are estimates (characters / 4); prompt and completion tokens come from Ollama's `prompt_eval_count` / `eval_count`.
