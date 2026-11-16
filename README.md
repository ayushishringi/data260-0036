# data260-0036

DATA-260 Homework 1. Personal configuration is derived from SJSU SID4 `0036`.

| Value | Result |
| --- | --- |
| SID4 | 0036 |
| PORT_BASE | 8036 |
| PREFIX | s0036 |
| SEED | 0036 |
| VERIFY_SEED | 260036 |
| DOMAIN_ID | 4 (open-source package vulnerabilities) |

Hardware used while authoring: MacBook Pro, Apple M5 Pro, 24 GB. Local model: `qwen3:4b` (already pulled). `qwen3:8b` was not used because a 4B tool-capable Qwen3 model was already local and fits interactive demo + 40-run latency collection on this machine.

## Run the form (localhost)

```bash
make run-web
# or: python3 -m http.server 8036
```

Open http://127.0.0.1:8036/

## Docker

```bash
docker compose up --build
```

The container serves the same static app on host port **8036**.

## Agents (Part 2)

Ollama must be running (`ollama serve`) with `qwen3:4b` (or set `OLLAMA_MODEL`).

```bash
python3 agents_demo.py --input reports/hw01/cases/nondeterminism_input.json
```

## Token-accounting client (Part 4)

```bash
python3 hw1_client.py
# interactive: python3 hw1_client.py --interactive
```

`/stats` prints turn count, cumulative tokens, and serialized history length without appending to history.

## Non-determinism (Part 3)

```bash
python3 scripts/run_nondeterminism.py
```

Writes `reports/hw01/raw/nondeterminism_40_runs.json` and `.csv`.

## Verify

```bash
make verify-hw01
```

## AWS ECS

Docker image used for deployment:

`docker.io/ayushishringii/data260-0036-hw1:latest`

The application was deployed in `us-west-2` as one AWS ECS Fargate task using Linux/ARM64, a public IP, and TCP port `8036`. The deployment was verified in the browser and captured in `reports/hw01/report.pdf`. The ECS service and cluster were deleted after collecting evidence.

## Why conversation context is resent (Part 4)

Stateless chat APIs do not store your session. Each `complete()` call sends the full `messages` list so the model can see prior turns. A **system** prompt is standing instruction (here: bullet-only review). A **user** message is the current request. Input tokens grow because every later turn includes all earlier messages. Growth is limited by the model context window, plus any truncation/summarization you add in the client.

## HW10: evaluation, judge validation, tracing and dashboard

Needs Kafka (`docker-compose.hw8.yml`), Redis Stack (`docker-compose.hw9.yml`), MySQL and Ollama `qwen3:4b`.

```bash
make e2e-hw10        # Part 2 + 4.2: three evaluated questions, a cache hit and an injected Writer failure
make cases-hw10      # Part 3.1: eval_cases.json (20 Writer drafts) and an empty human_labels.csv
make label-hw10      # Part 3.1: hand labeling; commit both files before the next step
make judge-hw10      # Part 3.2-3.3: judge x 3 runs (refuses if the labels are not committed)
make latency-hw10    # Part 4.3: 50 confirmed cache misses + 10 cache hits
make metrics-hw10    # reports/hw10/METRICS.md
make dashboard-hw10  # Part 1: Streamlit dashboard on http://localhost:8038
make verify-hw10     # reports/hw10/verification.json
make report-hw10     # reports/hw10/Shringi_HW10.pdf
```
