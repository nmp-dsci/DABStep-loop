#!/usr/bin/env bash
# Smoke-test a demo URL. Asserts what makes this deployment what it claims to
# be: up, in demo mode, serving the committed evidence, and refusing to call a
# model. A deploy failing any of these fails the workflow.
#
#   ./scripts/demo_smoke.sh https://xyz.ap-southeast-1.awsapprunner.com
set -euo pipefail

BASE="${1:?usage: demo_smoke.sh <base-url>}"
BASE="${BASE%/}"
fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }

# 1. Health says demo, and a champion is registered.
health="$(curl -fsS --max-time 20 "$BASE/healthz")" || fail "health unreachable"
echo "$health" | grep -q '"mode":"demo"' || fail "mode is not demo: $health"
echo "$health" | grep -q '"champion":"v' || fail "no champion registered: $health"

# 2. The committed evidence is served: runs, the ledger, the tasks, the data sample.
n_runs="$(curl -fsS --max-time 20 "$BASE/api/runs" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
[[ "$n_runs" -gt 0 ]] || fail "no runs served"
n_ledger="$(curl -fsS --max-time 20 "$BASE/api/ledger" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
[[ "$n_ledger" -gt 0 ]] || fail "ledger is empty"
n_tasks="$(curl -fsS --max-time 20 "$BASE/api/tasks?split=all" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
[[ "$n_tasks" -eq 450 ]] || fail "expected 450 tasks, got $n_tasks"
curl -fsS --max-time 20 "$BASE/api/data/files" | grep -q 'payments.csv' || fail "data files not served"

# 3. The demo pack is present, or Ask is a dead end.
n_pack="$(curl -fsS --max-time 20 "$BASE/api/demo/pack" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["items"]))')"
[[ "$n_pack" -gt 0 ]] || fail "demo pack is empty"

# 4. Ask declines an unknown question instead of calling a model.
resp="$(curl -sS --max-time 30 -X POST "$BASE/api/ask" -H 'Content-Type: application/json' \
  -d '{"question":"what is the meaning of life"}')"
echo "$resp" | grep -q '"decline"' || fail "unknown question was not declined: ${resp:0:200}"

# 5. The React shell serves from the same origin, for a deep link too.
curl -fsS --max-time 20 "$BASE/" | grep -qi '<!doctype html' || fail "index did not render"
curl -fsS --max-time 20 "$BASE/loop" | grep -qi '<!doctype html' || fail "deep link did not render"

echo "SMOKE PASS: $BASE — mode=demo, $n_runs runs, $n_ledger ledger entries, $n_pack recorded questions, model calls refused"
