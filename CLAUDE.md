# CLAUDE.md — DABstep-loop

> Read [`AGENTS.md`](./AGENTS.md) first: what this is, the decisions, the layout,
> the loop. [`DESIGN.md`](./DESIGN.md) governs anything visual (viewer, Lavish
> artifacts, README figures). This file is a pointer plus the rules that bite.

## Quick reference

- `make smoke` · `make loop CYCLES=1` · `make dev` + `cd frontend && npm run dev`
- `uv run pytest -q` · `make lint` · `uv run python -m dabstep_loop.tracking.gate`
- MLflow: central (`make platform-up` → `make -C ../nmp-central-ai up`) → http://localhost:5000; `MLFLOW_TRACKING_URI` overrides

## Rules

- **Never score the 450 in this build.** `eval --split all` is gated behind a
  confirmation for that reason. No answer key is ever derived from the
  leaderboard's `task_scores`.
- **Billing.** Dev runs use the subscription: `.env` has `BILLING=subscription`
  and no `ANTHROPIC_API_KEY`. `llm.require_live()` refuses to start otherwise.
  The demo image has `DEMO_MODE=1` baked in and cannot call a model.
- **The optimiser may edit two files** (`agents/vN/system.md`, `helper.py`).
  If you are asked to "improve the agent", the answer is `make loop`, not a hand
  edit — a hand edit without a re-run fails the CI gate.
- **Run folders are immutable** once scored. Fix the code and re-run.
- **Visuals follow DESIGN.md**: tokens verbatim, assertion headings, one `<em>`
  per page, every number with its baseline. Never the Tailwind/DaisyUI fallback.
- Never add `.lavish/` to `.gitignore`.

## Delegating

Mechanical work (formatting, a scoped test file, a doc pass) can go to a
cheaper model. The optimiser prompt, the gate, the billing guard and the
deploy workflow are cross-cutting: review those changes with a stronger model
before merging.
