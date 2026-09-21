# DABstep-loop

A Claude Agent SDK agent for the [DABstep](https://huggingface.co/spaces/adyen/DABstep) benchmark, and the loop that improves it from its own failures.

## 1 · Result — two cycles took Haiku from 4 to 9 of the 10 gold tasks; the gate held the first

| | v0 (baseline) | v1 (cycle 1) | v2 (cycle 2) |
|---|---|---|---|
| dev split, 10 tasks with gold | **4/10** | 8/10 | **9/10** |
| easy (3) | 1 | 3 | 3 |
| hard (7) | 3 | 5 | 6 |
| fixed vs v0 | — | 49, 70, 1273, 1681, 1753 | 49, 70, 1273, 1681, 1753 |
| broken vs v0 | — | 1871 | none |
| McNemar, one-sided | — | p = 0.109 → **held** | p = 0.031 → **promoted** |

v0 is NVIDIA's inference prompt on Haiku 4.5 with a thin helper. v1 is what one optimiser session (Sonnet 5, 40 turns, 3.85M input tokens) wrote after reading v0's six failed traces: uniform null-as-wildcard fee matching, volume-based monthly fraud rates, natural-month bucketing, four prompt rules. It passed eight, but computed task 1871's delta with a specificity tie-break the gold does not use; five fixes against one break is p = 0.109 on a one-sided exact McNemar test, so the gate held it (five fixes and no break, p = 0.031, would have cleared it). The offline reflection pass then found and verified the root cause against the data and recorded it in the ledger. Cycle 2's optimiser was shown v0's failures, cycle 1's per-task outcomes, that note, and `agents/v1/` as a held starting point: it kept v1's helper, removed `best_matching_fee`, added additive `fee_total_for_rule` / `total_fees_paid`, and left 2697 alone rather than guess — v2 passes 9, breaks nothing, and is the champion. Source: `runs/`, `loop/ledger.jsonl`, `agents/v2/diagnosis.json`.

The 450 leaderboard tasks are **not scored** in this build (deferred M8), and no answer key is derived from other teams' submissions. For scale: NVIDIA's Data Explorer reports 87.50% easy / 89.95% hard on the leaderboard with the same model; the plain Sonnet 4 ReAct baseline is 81.94 / 19.84.

## 2 · The loop — one session sees every failure, edits two files, and a gate decides

```
make smoke        v0 on the dev split → runs/<id>/ (results, traces, submission), logged to MLflow
make loop         eval champion → optimiser session → agents/v(N+1) → eval → gate → ledger
make reflect      read-only review of a run's traces → ledger notes for the next optimiser
```

- The optimiser is one `ClaudeSDKClient` session with Read/Write/Edit/Bash. A `PreToolUse` hook refuses writes outside `agents/v(N+1)/`; `agent.yaml` is frozen; a checksum of the guarded paths is compared after the session. It must verify helper changes against the dev gold in-session and finish with `diagnosis.json`.
- `loop/ledger.jsonl` is committed. Every diagnosis, every change, every verdict; per-task prior attempts are rendered into the next optimiser's prompt so a failed fix is not retried unchanged, and a held challenger is offered as a starting point.
- The gate (`eval/compare.py`): a one-sided exact McNemar test on the paired tasks, promote at p < 0.05; the verdict carries b (fixed), c (broken) and p. CI re-scores the champion's committed results with the vendored scorer and fails if the registry, the run and the agent folder disagree.

## 2b · The unsupervised loop — the 450 by family, probed, judged without answers

Ten gold tasks anchor six of the twelve question families the 450 fall into; the other six (188 of the 378 hard tasks) can only be learned from the 450 themselves, which have no answers. `make uloop` does that without ever scoring them:

```
make families     lens 1: the 106 templates → 12 operation families (an ordered regex table) → loop/families/families.json
make lenses       lenses 2+3: local MiniLM k-means, then one Sonnet membership pass; ARI + confusion + boundary tasks → lenses.json
make probe        a seeded sample (k per family, boundary tasks first, invariant siblings, never a dev id) run unscored, 2 passes
make ureflect RUN=<probe>   one read-only Sonnet session → loop/families/Fnn.json: canonical method, entry point, prompt rule, status
make uloop        probe champion → cards → optimiser (cards in its prompt) → dev-10 + the same probe on the challenger → gate A → ledger
```

- **Signals, none of which read gold** (`loop/signals.py`): S1 the share of a family's traces on its modal method; S2 agreement between two passes; S3 metamorphic invariants between sibling answers (`ids(day) ⊆ ids(month) ⊆ ids(year)`, `fees(month) ≤ fees(year)`, a month delta has the year's sign, min-scheme ≠ max-scheme…); S5 the guideline's format. S4 is the reflector's audit.
- **Gate A** (`eval/compare.gate_a`): promote when no dev task broke *and* the paired gold-free composite improved on the same seeded sample (invariants passed up with failures not up, or S1 up with S3 not worse; S5 and errors not worse). The McNemar p is recorded, not required: with one dev failure left it cannot clear 0.05.
- A probe run has `correct: null` on every row and writes no submission; the CI gate refuses a version whose prompt quotes a leaderboard question verbatim. The viewer's **Families** page shows the coverage, the cards, the three-lens confusion matrix and each family's paired signals across cycles.

## 2c · The harness — where the tokens went, and the profile that stops it

The "tokens per question" number was never the agent. Logging the request bodies of one dev task showed every API call carrying **95,810 characters of tool schemas for 49 Gmail, Calendar and Drive connectors** the CLI loads from the user-level claude.ai config — 27k tokens beside our 2.7k of prompt and tool, 91% of every call, never called. `agent/harness.py` names what a session carries besides the agent's files:

| profile | strict MCP | title call | tool output | when |
|---|---|---|---|---|
| `baseline` | inherits the user's connectors | yes | 12k-char truncation | how every run before s02 was made |
| `lean` | only our `py` server | off | as baseline | the fix; same answers, same trajectories |
| `lean-prune` | only ours | off | over 1,500 chars → head + `out#k`, `show()` re-opens | NVIDIA's "an id where the output was" |

`make eval HARNESS=lean` records the profile in `run.json`; the fingerprint is untouched. `make harness-experiment` runs v2 on dev-10 under all three, twice each, and `dabstep harness-compare` writes `loop/harness_experiment.json` (§2c of the findings in `.lavish/s03_*`). The loop's own sessions (optimiser, reflectors, lenses) set `strict_mcp_config` too, and the CI gate refuses a `ClaudeAgentOptions` without it.

## 3 · The agent — Haiku 4.5, one tool, two editable files

`agents/vN/system.md` (prompt) · `agents/vN/helper.py` (importable as `helper` inside the tool) · `agents/vN/agent.yaml` (frozen: `max_turns 20`, `timeout_s 270`, `tools [mcp__py__execute_python]`). The tool is an in-process MCP server: a persistent namespace with pandas preloaded, 120s per call, and NVIDIA's loop-breaker. Answers are scored with `question_scorer` vendored verbatim from the benchmark space.

## 4 · Run it

```
make setup && make data          # uv + npm; downloads the dataset (payments.csv is gitignored)
make platform-up                 # central MLflow (make -C ../nmp-central-ai up) → http://localhost:5000
cp .env.example .env             # BILLING=subscription, no key: dev runs bill the Claude subscription
make smoke                       # needs `claude login`
make loop CYCLES=1
make dev  &  cd frontend && npm run dev     # viewer on :5173, API on :8080
```

The viewer shows the data, the tasks, the architecture, every run and trace, the gate between any two runs, the ledger, an **Evolution** page that diffs any two agent versions alongside the optimiser's reasoning, and an **Ask** page that streams a live session in dev. Live demo: **https://xqcd7prnag.ap-southeast-1.awsapprunner.com**. Merging to `main` builds the same viewer into a read-only image (`DEMO_MODE=1` baked into the Dockerfile; no key, no login) and deploys it to App Runner via GitHub OIDC — the public URL replays the recorded pack and cannot bill.

## 5 · Where things are

See [`AGENTS.md`](AGENTS.md) for the layout, the decisions and their reasons, and the prerequisites; [`DESIGN.md`](DESIGN.md) for the visual brief; `.lavish/s00_dabstep-loop-init-plan.html` for the plan build 1 was built to and `.lavish/s01_unsupervised-reflection-plan.html` for build 2.
