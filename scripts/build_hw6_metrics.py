"""Build reports/hw06/METRICS.md from reports/hw06/raw/memory_cost_comparison.json."""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "reports" / "hw06" / "raw"
OUTPUT = ROOT / "reports" / "hw06" / "METRICS.md"
COMPONENTS = ["system_primer", "file_memory", "long_term_summary", "short_term_window", "episodic_facts"]


def pct(new: float, old: float) -> str:
    return f"{(new - old) / old * 100:+.1f}%"


def main() -> None:
    data = json.loads((RAW / "memory_cost_comparison.json").read_text(encoding="utf-8"))
    settings = {item["setting"]: item for item in data["settings"]}
    rows = list(csv.DictReader((RAW / "per_turn_tokens.csv").open(encoding="utf-8")))
    exp = data["experiment"]
    lines = [
        "# HW6 Part 3: Memory Cost Metrics",
        "",
        f"Model: Ollama `{exp['model']}` (num_ctx {exp['ollama_num_ctx']}, seed {exp['ollama_seed']}). "
        f"Each setting ran in a fresh uvicorn process with `SHORT_TERM_N`/`MEMORY_POLICY` set, in a fresh "
        f"session, with the same {exp['conversation_turns']}-message conversation, followed by the "
        f"{exp['probe_count']} probes in `memory_probes.yaml`. Per-turn means cover the 30 conversation turns. "
        "Raw data: `raw/memory_cost_comparison.json`, `raw/per_turn_tokens.csv`, `raw/chat_costs.jsonl`.",
        "",
        "## Results",
        "",
        "| Setting | Mean prompt tokens/turn | Mean latency (ms) | Probe quality (1-5) |",
        "|---|---:|---:|---:|",
    ]
    for name, item in settings.items():
        lines.append(
            f"| `{name}` | {item['mean_prompt_tokens_per_turn']:,.1f} | {item['mean_latency_ms']:,.0f} "
            f"| {item['probe_quality_mean']:.1f} |"
        )
    lines += [
        "",
        "## Probe scores (planted turn → score)",
        "",
        "| Setting | " + " | ".join(
            f"{p['id']} (t{p['planted_at_turn']})" for p in next(iter(settings.values()))["probe_results"]
        ) + " |",
        "|---|" + "---:|" * 5,
    ]
    for name, item in settings.items():
        lines.append(f"| `{name}` | " + " | ".join(str(p["score"]) for p in item["probe_results"]) + " |")
    lines += [
        "",
        "## Mean estimated tokens per prompt component (conversation turns)",
        "",
        "| Setting | " + " | ".join(COMPONENTS) + " | messages in window |",
        "|---|" + "---:|" * (len(COMPONENTS) + 1),
    ]
    for name in settings:
        turns = [row for row in rows if row["setting"] == name and row["kind"] == "conversation"]
        means = [statistics.mean(float(row[c]) for row in turns) for c in COMPONENTS]
        window = statistics.mean(float(row["short_term_message_count"]) for row in turns)
        lines.append(f"| `{name}` | " + " | ".join(f"{m:,.0f}" for m in means) + f" | {window:.1f} |")

    base, policy = settings.get("N=12,window"), settings.get("N=12,compressed_window")
    if base and policy:
        lines += [
            "",
            "## Compression policy vs. its baseline (both N=12)",
            "",
            "`compressed_window` keeps the last N messages but cuts every assistant reply except the latest "
            "to 240 characters; user messages stay verbatim, and the session summary and episodic facts carry the rest.",
            "",
            "| Metric | `N=12,window` | `N=12,compressed_window` | Change |",
            "|---|---:|---:|---:|",
            f"| Mean prompt tokens/turn | {base['mean_prompt_tokens_per_turn']:,.1f} | "
            f"{policy['mean_prompt_tokens_per_turn']:,.1f} | "
            f"{pct(policy['mean_prompt_tokens_per_turn'], base['mean_prompt_tokens_per_turn'])} |",
            f"| Mean short-term window tokens/turn | {base['mean_short_term_window_tokens']:,.1f} | "
            f"{policy['mean_short_term_window_tokens']:,.1f} | "
            f"{pct(policy['mean_short_term_window_tokens'], base['mean_short_term_window_tokens'])} |",
            f"| Input tokens / 30-turn conversation | {base['conversation_input_tokens']:,} | "
            f"{policy['conversation_input_tokens']:,} | "
            f"{pct(policy['conversation_input_tokens'], base['conversation_input_tokens'])} |",
            f"| Mean latency (ms) | {base['mean_latency_ms']:,.0f} | {policy['mean_latency_ms']:,.0f} | "
            f"{pct(policy['mean_latency_ms'], base['mean_latency_ms'])} |",
            f"| Probe quality | {base['probe_quality_mean']:.1f} | {policy['probe_quality_mean']:.1f} | "
            f"{policy['probe_quality_mean'] - base['probe_quality_mean']:+.1f} |",
        ]

    lines += [
        "",
        f"## Estimated cost of {exp['conversations_costed']:,} 30-turn conversations",
        "",
        f"Input ${exp['input_price_per_million']:g}/M tokens, output ${exp['output_price_per_million']:g}/M tokens, "
        "using the measured input and output tokens of each 30-turn run (probes excluded).",
        "",
        "| Setting | Input tokens/conv | Output tokens/conv | Input cost | Output cost | Total cost | $ per probe-quality point |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    efficiency = {}
    for name, item in settings.items():
        cost = item["cost_10k_conversations"]
        efficiency[name] = cost["total_cost_usd"] / item["probe_quality_mean"]
        lines.append(
            f"| `{name}` | {item['conversation_input_tokens']:,} | {item['conversation_output_tokens']:,} | "
            f"${cost['input_cost_usd']:,.2f} | ${cost['output_cost_usd']:,.2f} | **${cost['total_cost_usd']:,.2f}** | "
            f"${efficiency[name]:,.2f} |"
        )
    best = min(efficiency, key=efficiency.get)
    worst = max(efficiency, key=efficiency.get)
    lines += [
        "",
        "## Best and worst settings",
        "",
        "Selection rule: total cost divided by mean probe quality (dollars per quality point), so a setting "
        "only counts as best if it is cheap without losing memory quality.",
        "",
        f"- Best: `{best}`: ${settings[best]['cost_10k_conversations']['total_cost_usd']:,.2f} for 10,000 "
        f"conversations at probe quality {settings[best]['probe_quality_mean']:.1f}.",
        f"- Worst: `{worst}`: ${settings[worst]['cost_10k_conversations']['total_cost_usd']:,.2f} for 10,000 "
        f"conversations at probe quality {settings[worst]['probe_quality_mean']:.1f}.",
        f"- Difference: ${settings[worst]['cost_10k_conversations']['total_cost_usd'] - settings[best]['cost_10k_conversations']['total_cost_usd']:,.2f}.",
        "",
        "## Limitations",
        "",
        "One run per setting with five keyword-scored probes; latency is from one Apple M5 Pro laptop running "
        "Ollama locally. Output tokens are priced at 5x input and depend on reply length, which memory does not "
        "control directly. Component token counts are estimates (characters / 4); prompt and completion tokens "
        "come from Ollama's `prompt_eval_count` / `eval_count`.",
    ]
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
