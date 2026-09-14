# DABstep-loop — every target is a thin wrapper over `uv run dabstep …`.
.DEFAULT_GOAL := help
AGENT ?= v0
MODEL ?=
SPLIT ?= dev
WORKERS ?= 2
PASSES ?= 1
CYCLES ?= 1
MLFLOW_PORT ?= 5600
MODEL_FLAG := $(if $(MODEL),--model $(MODEL),)

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n", $$1, $$2}'

setup: ## install python deps (uv) and frontend deps (npm)
	uv sync
	cd frontend && npm ci

data: ## download the DABstep dataset into data/ (context is gitignored)
	uv run dabstep data

mlflow-up: ## start the self-hosted MLflow tracking server on :$(MLFLOW_PORT)
	mkdir -p .mlflow
	uv run mlflow server --host 127.0.0.1 --port $(MLFLOW_PORT) \
	  --backend-store-uri sqlite:///.mlflow/mlflow.db --artifacts-destination .mlflow/artifacts

eval: ## run AGENT on SPLIT (MODEL=, WORKERS=, PASSES=)
	uv run dabstep eval --agent $(AGENT) --split $(SPLIT) --workers $(WORKERS) --passes $(PASSES) $(MODEL_FLAG)

smoke: ## the dev-10 with Haiku, the build's only live eval
	uv run dabstep eval --agent $(AGENT) --split dev --workers $(WORKERS)

score: ## re-score RUN=<run id>
	uv run dabstep score $(RUN)

compare: ## gate CHAMPION=<run> CHALLENGER=<run>
	uv run dabstep compare $(CHAMPION) $(CHALLENGER)

register: ## register RUN=<run id> as challenger
	uv run dabstep register $(RUN)

promote: ## promote RUN=<run id> to champion
	uv run dabstep promote $(RUN)

submit: ## validate RUN=<run id> submission for the leaderboard form
	uv run dabstep submit $(RUN)

loop: ## the error loop: CYCLES=1 cycles of eval → diagnose → new version → gate
	uv run dabstep loop --cycles $(CYCLES) --workers $(WORKERS)

reflect: ## one offline reflection pass over the champion's traces
	uv run dabstep reflect

ledger: ## print the loop ledger
	uv run dabstep ledger

snapshot: ## export MLflow to loop/mlflow_snapshot.json
	uv run dabstep snapshot

demo-pack: ## record the champion's dev-10 as the demo replay pack
	uv run dabstep demo-pack

dev: ## run the API on :8080 (frontend: cd frontend && npm run dev)
	uv run dabstep serve --port 8080

demo-up: ## build and run the demo image locally (no keys, DEMO_MODE=1)
	docker build -t dabstep-demo . && docker run --rm -p 8080:8080 dabstep-demo

test: ## pytest
	uv run pytest -q

lint: ## ruff + mypy (+ frontend design lint when node_modules exist)
	uv run ruff format --check src tests scripts && uv run ruff check src tests scripts && uv run mypy
	@test -d frontend/node_modules && (cd frontend && npm run lint:design) || true

fmt: ## ruff format + fix
	uv run ruff format src tests scripts && uv run ruff check --fix src tests scripts

.PHONY: help setup data mlflow-up eval smoke score compare register promote submit loop reflect ledger snapshot demo-pack dev demo-up test lint fmt
