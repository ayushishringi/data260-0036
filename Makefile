PYTHON ?= .venv/bin/python3
PORT ?= 8036
IMAGE ?= data260-0036-hw2:latest

.PHONY: run run-api run-web agents client verify-hw01 verify-hw02

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

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker compose up --build