PYTHON ?= python3
PORT ?= 8036
IMAGE ?= data260-0036-hw1:latest

.PHONY: run run-web agents client verify-hw01 docker-build docker-run

run: run-web

run-web:
	$(PYTHON) -m http.server $(PORT)

agents:
	$(PYTHON) agents_demo.py --input reports/hw01/cases/nondeterminism_input.json

client:
	$(PYTHON) hw1_client.py

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker compose up --build

verify-hw01:
	$(PYTHON) scripts/verify_hw01.py
