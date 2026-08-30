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

This repo includes `deploy/ecs-task-definition.json`. Push `data260-0036-hw1:latest` to ECR, replace `REPLACE_WITH_ECR_IMAGE_URI`, then create **one** Fargate task/service with an assigned public IP and security group allowing TCP 8036. AWS CLI is not installed on the authoring machine, so the live public-IP screenshot is taken after you deploy from an account you control.

## Why conversation context is resent (Part 4)

Stateless chat APIs do not store your session. Each `complete()` call sends the full `messages` list so the model can see prior turns. A **system** prompt is standing instruction (here: bullet-only review). A **user** message is the current request. Input tokens grow because every later turn includes all earlier messages. Growth is limited by the model context window, plus any truncation/summarization you add in the client.
