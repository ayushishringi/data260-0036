# data260-0036

DATA-260 homework repository for Ayushi Shringi (SID4 `0036`, PREFIX `s0036`, DOMAIN_ID 4: open-source package vulnerabilities). The same codebase is extended every homework, so shared code lives in `src/` and `scripts/`, and each homework's report and evidence live in its own `reports/hwNN/` folder.

## Homework index

| Homework | Topic | Report | Evidence folder | Submitted version | Verify |
| --- | --- | --- | --- | --- | --- |
| HW1 | Vulnerability report form (HTML/JS, Docker, AWS ECS), Planner/Reviewer agents on Ollama, non-determinism, token accounting | [report.pdf](reports/hw01/report.pdf) | [reports/hw01/](reports/hw01/) | [`hw1`](https://github.com/ayushishringi/data260-0036/tree/hw1) | `make verify-hw01` |
| HW2 | Agent graph: schema validation, turn ceiling, adversarial inputs | [report.pdf](reports/hw02/report.pdf) | [reports/hw02/](reports/hw02/) | branch [`hw2`](https://github.com/ayushishringi/data260-0036/tree/hw2) | `make verify-hw02` |
| HW3 | Retrieval: embeddings and retrieval-quality comparison | [report.pdf](reports/hw03/report.pdf) | [reports/hw03/](reports/hw03/) | [`hw3`](https://github.com/ayushishringi/data260-0036/tree/hw3) | `python scripts/verify_hw03.py` |
| HW4 | RAG, the N+1 query experiment, database index and EXPLAIN | [report.pdf](reports/hw04/report.pdf) | [reports/hw04/](reports/hw04/) | [`hw4`](https://github.com/ayushishringi/data260-0036/tree/hw4) | `python scripts/verify_hw4.py` |
| HW5 | Vulnerability reports in MySQL, MCP tools, fault injection | [report.pdf](reports/hw05/report.pdf) | [reports/hw05/](reports/hw05/) | tag [`hw5`](https://github.com/ayushishringi/data260-0036/tree/0108bb70377d70f451df943aed727b3320440ef2) | `make verify-hw05` |
| HW6 | Conversation memory: short-term window, compression, memory cost | [report.pdf](reports/hw06/report.pdf) | [reports/hw06/](reports/hw06/) | [`hw6`](https://github.com/ayushishringi/data260-0036/tree/hw6) | `make verify-hw06` |
| HW7 | Tool-calling agents: reliability, Reflexion, bike-share ReAct agent, prompt injection, safety gate | [Shringi_HW7.pdf](reports/hw07/Shringi_HW7.pdf) | [reports/hw07/](reports/hw07/) | [`hw7`](https://github.com/ayushishringi/data260-0036/tree/hw7) | `make verify-hw07` |
| HW8 | Planner / Writer / Reviewer pipeline over Kafka, failure handling | [Shringi_HW8.pdf](reports/hw08/Shringi_HW8.pdf) | [reports/hw08/](reports/hw08/) | [`hw8`](https://github.com/ayushishringi/data260-0036/tree/hw8) | `make verify-hw08` |
| HW9 | Redis view counter, semantic cache, threshold sweep, stale answers | [Shringi_HW9.pdf](reports/hw09/Shringi_HW9.pdf) | [reports/hw09/](reports/hw09/) | [`hw9`](https://github.com/ayushishringi/data260-0036/tree/hw9) | `make verify-hw09` |
| HW10 | Streamlit dashboard, GEval evaluator, judge validation, tracing and latency | [Shringi_HW10.pdf](reports/hw10/Shringi_HW10.pdf) | [reports/hw10/](reports/hw10/) | [`hw10`](https://github.com/ayushishringi/data260-0036/tree/hw10) | `make verify-hw10` |

Each `reports/hwNN/` folder holds that homework's report PDF, `METRICS.md`, `AI_USE.md`, `RUN_LOG.txt` (where kept), `raw/` results and `verification.json`. The submitted state of each homework is its tag (HW2: the `hw2` branch); the run commands for HW10 are in the HW10 section at the end of this file.

## HW1 details

Personal configuration is derived from SJSU SID4 `0036`.

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
