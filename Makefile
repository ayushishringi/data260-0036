PYTHON ?= .venv/bin/python3
PORT ?= 8036
IMAGE ?= data260-0036-hw2:latest

.PHONY: run run-api run-web agents client verify-hw01 verify-hw02 verify-hw05 test-hw05 faults-hw05 verify-hw06 test-hw06 experiments-hw06 migrate-hw07 test-hw07 lint verify-hw07 kafka-up kafka-down kafka-topics demo-hw08 test-hw08 experiments-hw08 verify-hw08 redis-up migrate-hw09 counter-hw09 cache-demo-hw09 sweep-hw09 stale-hw09 part4-hw09 test-hw09 metrics-hw09 verify-hw09 qa-api-hw09 agents-hw09 e2e-hw10 cases-hw10 label-hw10 judge-hw10 latency-hw10 dashboard-hw10 test-hw10 metrics-hw10 verify-hw10 report-hw10 test-hw11 kit-hw11 report-hw11 test

run: run-api

# All unit tests (what CI runs). Tests that need MySQL/Ollama/Redis/Kafka skip when those are not running.
test:
	$(PYTHON) -m unittest discover -s tests -t .

run-api:
	$(PYTHON) -m uvicorn backend.main:app --host 127.0.0.1 --port $(PORT)

run-web:
	$(PYTHON) -m http.server 8080

agents:
	$(PYTHON) agents_demo.py --input reports/hw01/cases/nondeterminism_input.json

client:
	$(PYTHON) hw1_client.py

verify-hw01:
	$(PYTHON) scripts/verify_hw01.py

verify-hw02:
	$(PYTHON) scripts/verify_hw02.py

test-hw05:
	PYTHONPATH=. $(PYTHON) scripts/run_hw5_tests.py

faults-hw05:
	PYTHONPATH=. $(PYTHON) scripts/run_hw5_faults.py

verify-hw05:
	PYTHONPATH=. $(PYTHON) scripts/verify_hw5.py

test-hw06:
	$(PYTHON) -m unittest -v tests.test_hw6_file_memory

experiments-hw06:
	$(PYTHON) scripts/run_hw6_memory_cost.py --configs 4:window 12:window 30:window 12:compressed_window

verify-hw06:
	PYTHONPATH=. $(PYTHON) scripts/verify_hw6.py

migrate-hw07:
	$(PYTHON) scripts/migrate_hw7_users.py

test-hw07:
	$(PYTHON) -m unittest -v tests.test_hw7_auth tests.test_hw7_tools

lint:
	.venv/bin/ruff check .

verify-hw07:
	PYTHONPATH=. $(PYTHON) scripts/verify_hw7.py

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker compose up --build

# ---- HW8: Kafka request/response, three-agent pipeline, failure behavior
kafka-up:
	docker compose -f docker-compose.hw8.yml up -d --build

kafka-down:
	docker compose -f docker-compose.hw8.yml down

kafka-topics:
	docker exec s0036-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe | grep -E '^Topic: s0036'

demo-hw08:
	$(PYTHON) homework_demo.py

test-hw08:
	$(PYTHON) -m unittest -v tests.test_hw8

experiments-hw08:
	$(PYTHON) -u scripts/run_hw8_failures.py all

verify-hw08:
	PYTHONPATH=. $(PYTHON) scripts/verify_hw8.py

# ---- HW9: Redis view counter, semantic cache in front of the HW8 agents, self-improving agents
HW9_AGENT_ENV = HW8_GROUNDED=1 HW8_GROUP_SUFFIX=_hw9 HW8_STATE_DIR=.hw8_state/hw9 HW8_LOG_DIR=reports/hw09/logs
AGENT ?= planner

redis-up:
	docker compose -f docker-compose.hw9.yml up -d

migrate-hw09:
	$(PYTHON) scripts/migrate_hw9.py

counter-hw09:
	$(PYTHON) scripts/run_hw9_counter.py

cache-demo-hw09:
	$(PYTHON) -u scripts/run_hw9_cache_demo.py

sweep-hw09:
	$(PYTHON) -u scripts/run_hw9_sweep.py

stale-hw09:
	$(PYTHON) -u scripts/run_hw9_stale.py

part4-hw09:
	$(PYTHON) -u scripts/run_hw9_part4.py

test-hw09:
	$(PYTHON) -m unittest -v tests.test_hw9

metrics-hw09:
	$(PYTHON) scripts/build_hw9_metrics.py

verify-hw09:
	PYTHONPATH=. $(PYTHON) scripts/verify_hw9.py

# one grounded agent per terminal (make agents-hw09 AGENT=writer), then run a script with HW9_EXTERNAL_AGENTS=1
agents-hw09:
	$(HW9_AGENT_ENV) $(PYTHON) -u $(AGENT).py

qa-api-hw09:
	$(PYTHON) -m uvicorn backend.qa_cache_api:app --host 127.0.0.1 --port 8037

# ---- HW10: evaluator agent (DeepEval GEval, local judge), judge validation, tracing, Streamlit dashboard
# Needs Kafka (make kafka-up), Redis (make redis-up), MySQL and `ollama serve`.
e2e-hw10:
	$(PYTHON) -u scripts/run_hw10_e2e.py

# Part 3 order: cases-hw10 -> label-hw10 (by hand) -> git commit eval_cases.json human_labels.csv -> judge-hw10
cases-hw10:
	$(PYTHON) -u scripts/build_hw10_eval_cases.py

label-hw10:
	$(PYTHON) scripts/label_hw10.py

judge-hw10:
	$(PYTHON) -u scripts/run_hw10_judge.py

latency-hw10:
	$(PYTHON) -u scripts/run_hw10_latency.py

dashboard-hw10:
	$(PYTHON) -m streamlit run dashboard/hw10_app.py --server.port 8038 --server.headless true

test-hw10:
	$(PYTHON) -m unittest -v tests.test_hw10

metrics-hw10:
	$(PYTHON) scripts/build_hw10_metrics.py

verify-hw10:
	PYTHONPATH=. $(PYTHON) scripts/verify_hw10.py

report-hw10:
	PYTHONPATH=. $(PYTHON) scripts/build_hw10_report.py

# HW11: stock-watch kit (stock-watch/). test-hw11 checks the fixtures mechanically in a throwaway copy
# (every item decided quiet, so it never tests the golden labels); kit-hw11 builds the zip for Muse
# without gold_0036.json, so the agent cannot read the expected decisions before it decides.
test-hw11:
	bash scripts/check_hw11_fixtures.sh "$(CURDIR)/stock-watch" "$$(mktemp -d)/stock-watch"

kit-hw11:
	rm -f reports/hw11/stock-watch-kit-0036.zip
	zip -qr reports/hw11/stock-watch-kit-0036.zip stock-watch -x 'stock-watch/state/*' 'stock-watch/digests/*' '*/__pycache__/*' '*.DS_Store' 'stock-watch/golden/gold_0036.json'
	unzip -l reports/hw11/stock-watch-kit-0036.zip | tail -1

report-hw11:
	$(PYTHON) scripts/build_hw11_report.py
