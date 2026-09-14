"""The CI gate: the committed champion is what the registry says it is.

Runs with no model and no server. It re-scores the champion run's committed
`results.jsonl` with the vendored scorer and checks three things: the pass
count matches the registry, the agent folder's bytes still hash to the
fingerprint the run was scored under, and no ledger cycle is left `pending`.
A prompt edit that forgets to re-run, or a hand edit to a run folder, fails here.
"""

from __future__ import annotations

import sys

from dabstep_loop.agent.versions import load_version
from dabstep_loop.data.tasks import load_tasks
from dabstep_loop.eval.runner import load_run
from dabstep_loop.eval.score import score_answer
from dabstep_loop.loop.ledger import read_ledger
from dabstep_loop.tracking.registry import read_registry


def check() -> list[str]:
    problems: list[str] = []
    reg = read_registry()
    champ = reg.get("champion")
    if not champ:
        return ["no champion in loop/registry.json"]
    meta, results = load_run(str(champ["run_id"]))
    gold = {t.task_id: t for t in load_tasks(str(champ["split"]))}
    rescored = sum(
        1 for r in results if r.task_id in gold and score_answer(gold[r.task_id], r.agent_answer)
    )
    if rescored != champ["passed"]:
        problems.append(
            f"champion {champ['agent']} re-scores to {rescored}, registry says {champ['passed']}"
        )
    version = load_version(str(champ["agent"]))
    if version.fingerprint != champ["fingerprint"]:
        problems.append(
            f"agents/{champ['agent']} hashes to {version.fingerprint}, but the champion run was scored on {champ['fingerprint']}: re-run `make smoke` and promote"
        )
    if meta.fingerprint != champ["fingerprint"]:
        problems.append(
            f"run {meta.run_id} fingerprint {meta.fingerprint} != registry {champ['fingerprint']}"
        )
    for e in read_ledger():
        if (e.get("outcome") or {}).get("verdict") == "pending":
            problems.append(f"ledger cycle {e.get('cycle')} is still pending")
    return problems


def main() -> int:
    problems = check()
    if problems:
        for p in problems:
            print(f"GATE FAIL: {p}", file=sys.stderr)
        return 1
    reg = read_registry()["champion"]
    print(
        f"GATE OK: champion {reg['agent']} ({reg['fingerprint']}) re-scores to {reg['passed']}/{reg['n_scored']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
