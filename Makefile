PYTHON ?= .venv/bin/python3
PORT ?= 8036
IMAGE ?= data260-0036-hw2:latest

.PHONY: run run-api run-web agents client verify-hw01 verify-hw02 verify-hw05 test-hw05 faults-hw05 verify-hw06 test-hw06 experiments-hw06 migrate-hw07 test-hw07 lint verify-hw07

run: run-api

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
