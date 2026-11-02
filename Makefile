.PHONY: setup check test test-int lint fmt data train eval up down infra-up infra-down infra-reset seed demo

PYTHON ?= .venv/bin/python
ifeq ($(OS),Windows_NT)
    PYTHON := .venv\Scripts\python.exe
    RUFF := .venv\Scripts\ruff.exe
    MYPY := .venv\Scripts\mypy.exe
    PYTEST := .venv\Scripts\pytest.exe
else
    RUFF := .venv/bin/ruff
    MYPY := .venv/bin/mypy
    PYTEST := .venv/bin/pytest
endif

setup:
	uv pip install -r requirements.txt --python $(PYTHON)

check: lint test

test:
	$(PYTEST) backend/tests -v --cov=backend/app --cov-report=term-missing

lint:
	$(RUFF) check backend
	$(MYPY) backend/app

fmt:
	$(RUFF) format backend
	$(RUFF) check --fix backend

data:
	$(PYTHON) scripts/generate_synthetic_data.py

train:
	$(PYTHON) ml/train_risk.py
	$(PYTHON) ml/train_layoutlm.py

eval:
	$(PYTHON) scripts/run_evaluations.py

up:
	docker compose up -d

down:
	docker compose down

infra-up:
	docker compose --env-file .env -f docker/compose.dev.yml up -d --wait

infra-down:
	docker compose --env-file .env -f docker/compose.dev.yml down

infra-reset:
	docker compose --env-file .env -f docker/compose.dev.yml down --volumes --remove-orphans
	docker compose --env-file .env -f docker/compose.dev.yml up -d --wait

test-int:
	$(PYTHON) -m pytest backend/tests -m integration -v

seed:
	$(PYTHON) scripts/seed_database.py

demo:
	$(PYTHON) scripts/run_demo.py
