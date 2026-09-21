# DABstep-loop — every target is a thin wrapper over `uv run dabstep …`.
.DEFAULT_GOAL := help
AGENT ?= v0
MODEL ?=
SPLIT ?= dev
WORKERS ?= 2
PASSES ?= 1
HARNESS ?= lean
CYCLES ?= 1
K ?= 3
SEED ?= 0
PROBE_PASSES ?= 2
PROBE_WORKERS ?= 3
MLFLOW_TRACKING_URI ?= http://localhost:5000
MODEL_FLAG := $(if $(MODEL),--model $(MODEL),)

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n", $$1, $$2}'

setup: ## install python deps (uv) and frontend deps (npm)
	uv sync
	cd frontend && npm ci

data: ## download the DABstep dataset into data/ (context is gitignored)
	uv run dabstep data

platform-up: ## start the central MLflow (nmp-central-ai: postgres + minio + mlflow on :5000)
	$(MAKE) -C ../nmp-central-ai up

platform-status: ## preflight: the central MLflow must answer /health (runs before every tracked eval)
	@curl -fsS $(MLFLOW_TRACKING_URI)/health >/dev/null || (echo "central MLflow down at $(MLFLOW_TRACKING_URI): run make platform-up"; exit 1)

eval: platform-status ## run AGENT on SPLIT (MODEL=, WORKERS=, PASSES=, HARNESS=lean|baseline|lean-prune)
	uv run dabstep eval --agent $(AGENT) --split $(SPLIT) --workers $(WORKERS) --passes $(PASSES) --harness $(HARNESS) $(MODEL_FLAG)

smoke: platform-status ## the dev-10 with Haiku, the build's only live eval
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

loop: platform-status ## the error loop: CYCLES=1 cycles of eval → diagnose → new version → gate
	uv run dabstep loop --cycles $(CYCLES) --workers $(WORKERS)

families: ## lens 1: the 450 by operation family → loop/families/families.json
	uv run dabstep families

lenses: ## lenses 2+3: local embeddings + one Sonnet membership pass → loop/families/lenses.json
	uv run dabstep lenses

probe: ## unscored probe of the 450 by family (AGENT=v2 K=3 SEED=0 PROBE_PASSES=2 PROBE_WORKERS=3)
	uv run dabstep probe $(if $(filter-out v0,$(AGENT)),--agent $(AGENT),) --k $(K) --seed $(SEED) --passes $(PROBE_PASSES) --workers $(PROBE_WORKERS)

harness-experiment: platform-status ## s02: v2 on dev-10 under baseline, lean and lean-prune, two passes each, then compare
	for h in baseline lean lean-prune; do for p in 1 2; do uv run dabstep eval --agent $(AGENT) --split dev --workers 3 --harness $$h --note "s02 harness experiment $$h pass $$p"; done; done
	uv run dabstep harness-compare --agent $(AGENT)

harness-compare: ## compare the s02 arms already in runs/
	uv run dabstep harness-compare --agent $(AGENT)

ureflect: ## unsupervised reflection over a probe RUN=<run id> → loop/families/Fnn.json
	uv run dabstep ureflect $(RUN)

uloop: platform-status ## the unsupervised loop: CYCLES=1 of probe → cards → optimiser → paired eval → gate A
	uv run dabstep uloop --cycles $(CYCLES) --k $(K) --seed $(SEED) --passes $(PROBE_PASSES) --workers $(PROBE_WORKERS)

reflect: ## one offline reflection pass over the champion's traces
	uv run dabstep reflect

ledger: ## print the loop ledger
	uv run dabstep ledger

snapshot: platform-status ## export MLflow to loop/mlflow_snapshot.json
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

.PHONY: help setup data platform-up platform-status eval smoke score compare register promote submit loop reflect ledger snapshot demo-pack dev demo-up test lint fmt
