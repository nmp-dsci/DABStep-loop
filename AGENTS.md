# AGENTS.md — DABstep-loop

The source of truth for how this project is built and why. `CLAUDE.md` points
here. `DESIGN.md` governs anything visual. The plan this was built to is
`.lavish/s00_dabstep-loop-init-plan.html`.

## 1 · What it is — a Haiku agent for DABstep, and the loop that improves it

[DABstep](https://huggingface.co/spaces/adyen/DABstep) is 450 tabular-QA tasks
over a payments dataset (a 138k-row `payments.csv`, 1000 fee rules, a manual).
The 450 have no published answers; a `dev` split of 10 does. This project:

1. runs a Claude Agent SDK agent (Haiku 4.5, one stateful Python tool) over the
   dev split and scores it with the leaderboard's own scorer, vendored verbatim;
2. tracks every run as a folder under `runs/` and indexes it in a self-hosted
   MLflow;
3. runs an **error loop**: one optimiser session (Sonnet) reads every failed
   trace and the ledger of earlier attempts, writes `agents/v(N+1)/{system.md,
   helper.py}`, and a gate promotes it when a one-sided McNemar test on the paired
   tasks clears p < 0.05;
4. serves a read-only viewer (React + FastAPI) of the data, the architecture,
   the runs, the gate and the ledger, deployed to App Runner on merge to main.

It replicates the shape of NVIDIA's 1st-place "Data Explorer" recipe
(Haiku 4.5, python executor, a helper module distilled from failures, offline
reflection) on the Agent SDK. **This build never scores the 450.** The Sonnet
baseline, full runs and a leaderboard submission are the deferred M8.

## 2 · Decisions, and the reasons

| Decision | Choice | Why |
|---|---|---|
| Labels | dev-10 gold only (NVIDIA protocol) | an answer key derived from other teams' `task_scores` would be training on the test set |
| Model under test | `claude-haiku-4-5` | the recipe being replicated; the cheap model is the one worth improving |
| Optimiser | `claude-sonnet-5`, effort medium (`llm.EFFORT`, shared by every SDK session), one session per cycle | must read ~10 traces and the manual and verify a helper in one context |
| Optimiser surfaces | `system.md`, `helper.py` only; `agent.yaml` frozen | a comparison is between prompts and helpers, not budgets |
| Tracking | MLflow 3, sqlite, `:5600`, self-hosted | the user's requirement; the run folder is the record, MLflow the index |
| Billing | subscription in dev via the CLI; demo image cannot call a model | `llm.py` blanks `ANTHROPIC_API_KEY`, strips `CLAUDE_CODE_*`, refuses if both a key and `BILLING=subscription` are set |
| Deploy | ConvFinQA's pattern: ECR + App Runner, OIDC role, `workflow_run` after CI, `DEMO_MODE=1` in the Dockerfile | keyless by construction |
| Region | `ap-southeast-1` | `ap-southeast-2` is at this account's two-service App Runner cap |
| Frontend | React 18 + Vite + TS, plain CSS on `tokens.css` | the Field Guide brief (`DESIGN.md`); no Tailwind/DaisyUI |

## 3 · Layout

```
agents/vN/            system.md · agent.yaml (frozen) · helper.py · diagnosis.json (written by the optimiser,
                      carries a `changes[]` change log) · change_log.json (only on versions written before
                      that contract; `dabstep annotate vN` backfills it, labelled source=post-hoc)
data/tasks/           dev.jsonl (10, gold) · all.jsonl (450, no gold)     committed
data/samples/         every context file; payments.csv first 500 rows       committed
data/context/         the full download (`make data`)                        gitignored
runs/<id>/            run.json · results.jsonl · submission.jsonl · agent/ · traces/<task>.json
loop/ledger.jsonl     one entry per cycle: diagnoses + outcome (kinds: cycle · reflect · ureflect · ucycle)
loop/families/        families.json (lens 1) · lenses.json (lenses 2+3) · Fnn.json (one card per family, written by the reflector)
loop/registry.json    champion / challenger aliases (mirrored to MLflow)
loop/mlflow_snapshot.json  `make snapshot`, for the demo image
src/dabstep_loop/
  config.py           paths + Settings (boots keyless)
  data/               download · tasks · file_structures
  agent/              llm.py (models, billing) · versions.py · prompt.py · session.py · answer.py · tools/python_executor.py
  eval/               scorer.py (vendored) · score.py · runner.py · compare.py (gate) · submission.py
  tracking/           mlflow_log.py · registry.py · snapshot.py · gate.py (CI)
  loop/               run.py · optimiser.py · ledger.py · reflect.py · families.py · lenses.py · slots.py · sampler.py · invariants.py · signals.py · ureflect.py
  serving/            app.py (FastAPI + SPA) · demo_pack/ (build + pack.json)
frontend/             Vite + React; src/tokens.css verbatim from DESIGN.md; scripts/design_lint.mjs
infra/terraform/      bootstrap (OIDC role, run once locally) · demo (ECR + App Runner)
.github/workflows/    ci.yml · deploy-aws.yml
```

## 4 · Commands

```
make setup            uv sync + npm ci
make data             download the dataset; regenerate data/samples and file_structures.json
make mlflow-up        MLflow on :5600 (sqlite under .mlflow/)
make smoke            v0-style Haiku run on the dev split → runs/<id>/, logged to MLflow
make eval AGENT=v1 SPLIT=dev WORKERS=3 [MODEL=sonnet] [PASSES=3]
make compare CHAMPION=<run> CHALLENGER=<run>
make promote RUN=<run>        make register RUN=<run>
make loop CYCLES=1            eval → optimiser session → challenger eval → gate → ledger
make reflect                  offline reflection over the champion's traces → ledger entry
make families · make lenses   the 450 by family (lens 1), then embeddings + a Sonnet membership pass (lenses 2+3)
make probe [K=3 SEED=0]       unscored probe of the champion on a seeded per-family sample, 2 passes
make ureflect RUN=<probe>     unsupervised reflection → loop/families/Fnn.json
make uloop CYCLES=1           probe → cards → optimiser → paired eval → gate A → ledger
make snapshot · make demo-pack  export for the demo image
make dev                      API on :8080; `cd frontend && npm run dev` for the UI on :5173
make demo-up                  build + run the demo image locally
make test · make lint
```

The `eval` command refuses `SPLIT=all` without an interactive confirmation.

## 5 · The loop, precisely

1. `run_cycle` loads the registry champion; reuses its run if the folder's
   fingerprint matches, else re-evaluates.
2. Failures = `correct is False or error`. None → ledger `nothing to fix`, stop.
3. `run_optimiser` copies the champion to `agents/v(N+1)/`, builds one prompt
   (both surfaces, every failure's question/gold/answer/condensed trace,
   `render_history()` of the ledger incl. per-task prior attempts), and runs
   one `ClaudeSDKClient` session with Read/Write/Edit/Bash/Glob/Grep. A
   `PreToolUse` hook denies writes outside the new folder; a checksum of the
   guarded paths (`agents/`, `src/dabstep_loop/{agent,eval,loop,data}`,
   `tests/`, `data/tasks/`, …) is compared before and after; `agent.yaml`
   must be byte-identical; `diagnosis.json` must exist.
4. The ledger entry is appended **before** the challenger runs (verdict
   `pending`), then `update_entry` fills `outcome` after `compare()` — a
   one-sided exact McNemar test on the discordant tasks, promote at p < 0.05.
5. Promote → registry champion; hold → registry challenger. Either way the
   version folder and its run stay in the repo.

## 5b · The unsupervised cycle, precisely

1. `run_ucycle` evaluates the champion on dev-10 as above, then **probes** it:
   `sampler.draw(k, seed)` takes k tasks per family from the 450 (boundary
   tasks from `lenses.json` first, never a dev id, plus the siblings each
   invariant needs), `run_eval(score=False, passes=2)` runs them with gold
   blanked into `runs/<ts>_vN_probe_haiku/` (`kind: probe`, `correct: null`,
   no submission), and `signals.compute` writes `signals.json` next to it. A
   finished probe of the same bytes, k, seed and passes is reused.
2. If any card is missing or cites another probe, `ureflect.run_ureflection`
   runs one read-only Sonnet session over the family blocks (traces side by
   side, S1–S3, S5, the current card, the dev anchors) and the harness writes
   `loop/families/Fnn.json` from its JSON reply; ledger kind `ureflect`.
3. `run_optimiser(..., families_block=render_families_block(probe))` is the
   same session as §5 with the cards (worst status first) and every failed
   invariant's two traces appended, plus rules 4b–4d: one routing row and at
   most one blanked example per family in `system.md`, one entry point per
   family in `helper.py`, verified in-session against an invariant, never
   against a leaderboard answer. `loop/families/` is in `GUARDED`.
4. The challenger runs dev-10 (scored) and the same probe sample (unscored);
   `compare.gate_a` decides; the ledger entry (kind `ucycle`) carries
   `signals_before`, `signals_after` and `signals_by_family`.
5. Lenses 2 and 3 (`lenses.py`) are computed once by `dabstep lenses` and
   only say how far to trust lens 1 per task; the family id on a card is
   always the regex family.

## 6 · Conventions

- `uv` for everything Python; Ruff (line 100); mypy strict; pytest offline only.
- Models are named in `agent/llm.py` and nowhere else.
- Never commit `.env`, keys, `data/context/`, `.mlflow/`. Never add `.lavish/`
  to `.gitignore`.
- A number on a page has its denominator; a figure has a committed source.
- Commit messages: imperative subject, a body that says why.

## 7 · Prerequisites that sit with the author

- `claude login` (subscription) for any live run.
- One-off `terraform apply` in `infra/terraform/bootstrap` with admin
  credentials before the first deploy; then `DEPLOY_ROLE_ARN` in
  `deploy-aws.yml` matches its output.
