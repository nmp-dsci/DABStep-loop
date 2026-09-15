"""The CI gate: the committed champion is what the registry says it is.

Runs with no model and no server. It re-scores the champion run's committed
`results.jsonl` with the vendored scorer and checks three things: the pass
count matches the registry, the agent folder's bytes still hash to the
fingerprint the run was scored under, and no ledger cycle is left `pending`.
A prompt edit that forgets to re-run, or a hand edit to a run folder, fails here.
"""

from __future__ import annotations

import sys

from dabstep_loop.agent.versions import AgentVersion, load_version
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
    problems += check_families(version)
    problems += check_harness()
    return problems


def check_harness() -> list[str]:
    """Every SDK session in the package names `strict_mcp_config` (s02).

    Without it the CLI loads the user's claude.ai connector tools into every
    call — measured at 27k tokens per call, 91% of the champion's prefix. The
    task session takes it from its harness profile; the loop sessions must set
    it explicitly, so a new session cannot inherit the bloat by omission."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1]
    problems: list[str] = []
    for f in sorted(src.rglob("*.py")):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"ClaudeAgentOptions\(", text):
            block = text[m.end() : m.end() + 1500].split("\n)")[0]
            if "strict_mcp_config" not in block:
                line = text.count("\n", 0, m.start()) + 1
                problems.append(
                    f"{f.relative_to(src)}:{line} ClaudeAgentOptions without strict_mcp_config"
                )
    return problems


def check_families(version: AgentVersion) -> list[str]:
    """Every card's evidence run exists, and the champion's surfaces quote no leaderboard question."""
    from dabstep_loop.config import RUNS_DIR
    from dabstep_loop.loop.ureflect import read_cards

    problems: list[str] = []
    for fid, card in read_cards().items():
        run = str(card.get("probe_run") or "")
        if run and not (RUNS_DIR / run / "signals.json").exists():
            problems.append(f"card {fid} cites probe {run}, which has no signals.json in runs/")
        if card.get("status") not in {"verified", "provisional", "open"}:
            problems.append(f"card {fid} has status {card.get('status')!r}")
    surfaces = " ".join(version.files().get(s, "") for s in ("system.md", "helper.py")).lower()
    quoted = [
        t.task_id
        for t in load_tasks("all")
        if len(t.question) >= 40 and t.question.lower() in surfaces
    ]
    if quoted:
        problems.append(
            f"agents/{version.name} quotes leaderboard questions verbatim: tasks {quoted[:5]} — examples must use blanks"
        )
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
