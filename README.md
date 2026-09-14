# DABstep-loop

A Claude Agent SDK agent for the [DABstep](https://huggingface.co/spaces/adyen/DABstep) benchmark, and the loop that improves it from its own failures.

## 1 · Result — one cycle took Haiku from 4 to 8 of the 10 gold tasks, and the gate still said no

| | v0 (baseline) | v1 (cycle 1 challenger) |
|---|---|---|
| dev split, 10 tasks with gold | **4/10** | **8/10** |
| easy (3) | 1 | 3 |
| hard (7) | 3 | 5 |
| fixed | — | 49, 70, 1273, 1681, 1753 |
| broken | — | 1871 |
| verdict | champion | **held** — a promoted version may not flip a task that passed |

v0 is NVIDIA's inference prompt on Haiku 4.5 with a thin helper. v1 is what one optimiser session (Sonnet 5, 40 turns, 3.85M input tokens) wrote after reading v0's six failed traces: uniform null-as-wildcard fee matching, volume-based monthly fraud rates, natural-month bucketing, four prompt rules. It passed eight, but computed task 1871's delta with a specificity tie-break the gold does not use, so the gate held it. The offline reflection pass then found and verified the root cause against the data and recorded it in the ledger for the next cycle. Source: `runs/`, `loop/ledger.jsonl`.

The 450 leaderboard tasks are **not scored** in this build (deferred M8), and no answer key is derived from other teams' submissions. For scale: NVIDIA's Data Explorer reports 87.50% easy / 89.95% hard on the leaderboard with the same model; the plain Sonnet 4 ReAct baseline is 81.94 / 19.84.

## 2 · The loop — one session sees every failure, edits two files, and a gate decides

```
make smoke        v0 on the dev split → runs/<id>/ (results, traces, submission), logged to MLflow
make loop         eval champion → optimiser session → agents/v(N+1) → eval → gate → ledger
make reflect      read-only review of a run's traces → ledger notes for the next optimiser
```

- The optimiser is one `ClaudeSDKClient` session with Read/Write/Edit/Bash. A `PreToolUse` hook refuses writes outside `agents/v(N+1)/`; `agent.yaml` is frozen; a checksum of the guarded paths is compared after the session. It must verify helper changes against the dev gold in-session and finish with `diagnosis.json`.
- `loop/ledger.jsonl` is committed. Every diagnosis, every change, every verdict; per-task prior attempts are rendered into the next optimiser's prompt so a failed fix is not retried unchanged, and a held challenger is offered as a starting point.
- The gate (`eval/compare.py`): more passes **and** no pass→fail flip. CI re-scores the champion's committed results with the vendored scorer and fails if the registry, the run and the agent folder disagree.

## 3 · The agent — Haiku 4.5, one tool, two editable files

`agents/vN/system.md` (prompt) · `agents/vN/helper.py` (importable as `helper` inside the tool) · `agents/vN/agent.yaml` (frozen: `max_turns 20`, `timeout_s 270`, `tools [mcp__py__execute_python]`). The tool is an in-process MCP server: a persistent namespace with pandas preloaded, 120s per call, and NVIDIA's loop-breaker. Answers are scored with `question_scorer` vendored verbatim from the benchmark space.

## 4 · Run it

```
make setup && make data          # uv + npm; downloads the dataset (payments.csv is gitignored)
make mlflow-up                   # self-hosted MLflow on :5600
cp .env.example .env             # BILLING=subscription, no key: dev runs bill the Claude subscription
make smoke                       # needs `claude login`
make loop CYCLES=1
make dev  &  cd frontend && npm run dev     # viewer on :5173, API on :8080
```

The viewer shows the data, the tasks, the architecture, every run and trace, the gate between any two runs, the ledger, and an **Ask** page that streams a live session in dev. Merging to `main` builds the same viewer into a read-only image (`DEMO_MODE=1` baked into the Dockerfile; no key, no login) and deploys it to App Runner via GitHub OIDC — the public URL replays the recorded pack and cannot bill.

## 5 · Where things are

See [`AGENTS.md`](AGENTS.md) for the layout, the decisions and their reasons, and the prerequisites; [`DESIGN.md`](DESIGN.md) for the visual brief; `.lavish/s00_dabstep-loop-init-plan.html` for the plan this was built to.
