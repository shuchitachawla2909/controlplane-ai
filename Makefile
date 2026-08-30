# ControlPlane.ai — developer entrypoints
# Local dev needs Python 3.11+ and Node 18+. Docker path: `docker compose up --build`.

PYTHON ?= python
PIP ?= $(PYTHON) -m pip
BACKEND_DIR := backend
FRONTEND_DIR := frontend
VENV := $(BACKEND_DIR)/.venv

ifeq ($(OS),Windows_NT)
	VENV_PY := $(VENV)/Scripts/python.exe
else
	VENV_PY := $(VENV)/bin/python
endif

.PHONY: help setup setup-backend setup-frontend dev dev-backend dev-frontend \
        seed evaluate benchmark test test-unit test-integration lint clean

help:
	@echo "ControlPlane.ai targets:"
	@echo "  make setup       - create venv, install backend + frontend deps"
	@echo "  make dev         - run backend (:8000) and frontend (:5173) together"
	@echo "  make seed        - seed the synthetic enterprise + demo scenarios"
	@echo "  make evaluate    - run the labeled evaluation dataset, write results/"
	@echo "  make benchmark   - run 3-arm benchmark (no-checker / always-deep / controlplane)"
	@echo "  make test        - run the full backend test suite"
	@echo "  make clean       - remove venv, caches, local db and generated artifacts"

setup: setup-backend setup-frontend

setup-backend:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PY) -m pip install --upgrade pip
	$(VENV_PY) -m pip install -r $(BACKEND_DIR)/requirements.txt
	@echo "Backend ready. Optional PII/LLM extras: $(VENV_PY) -m pip install -r $(BACKEND_DIR)/requirements-optional.txt"

setup-frontend:
	cd $(FRONTEND_DIR) && npm install

dev:
	@echo "Starting backend + frontend. Use two terminals if this does not fork on your shell."
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd $(BACKEND_DIR) && ../$(VENV_PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd $(FRONTEND_DIR) && npm run dev

seed:
	cd $(BACKEND_DIR) && ../$(VENV_PY) ../scripts/seed_demo.py

evaluate:
	cd $(BACKEND_DIR) && ../$(VENV_PY) ../scripts/run_evaluation.py

benchmark:
	cd $(BACKEND_DIR) && ../$(VENV_PY) ../scripts/benchmark.py

test:
	cd $(BACKEND_DIR) && ../$(VENV_PY) -m pytest -q

test-unit:
	cd $(BACKEND_DIR) && ../$(VENV_PY) -m pytest -q tests/unit

test-integration:
	cd $(BACKEND_DIR) && ../$(VENV_PY) -m pytest -q tests/integration

clean:
	rm -rf $(VENV) $(BACKEND_DIR)/controlplane.db $(BACKEND_DIR)/.pytest_cache
	rm -rf $(FRONTEND_DIR)/node_modules $(FRONTEND_DIR)/dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
