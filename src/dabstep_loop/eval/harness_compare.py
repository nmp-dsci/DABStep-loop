"""The s02 harness experiment: the same agent under several harness profiles, compared.

Reads the run folders (one per arm per pass, all `kind: eval` on dev), and
writes `loop/harness_experiment.json`: per arm the tokens per question, the
cache classes from the SDK's own transcripts, calls, output tokens, passes per
task per pass, pruning re-opens, and the adoption verdict. The rule is per
task, not a p-value: an arm is adoptable when nothing that passed on every
baseline pass fails on every one of its passes, and its mean passes per run
are not below the baseline's.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dabstep_loop.config import LOOP_DIR, RUNS_DIR
from dabstep_loop.eval.runner import RunMeta, list_runs, load_run

OUT = LOOP_DIR / "harness_experiment.json"
TRANSCRIPTS = Path.home() / ".claude" / "projects"

# Haiku 4.5 list prices, $/M — for the dollar view only; dev runs bill the subscription.
PRICE = {"fresh": 1.0, "cache_write": 1.25, "cache_read": 0.10, "output": 5.0}


@dataclass
class ArmStats:
    harness: str
    runs: list[str]
    n_tasks: int
    passes_per_run: list[int]
    input_tokens_mean: float  # per question, mean over runs
    input_tokens_by_task: dict[str, list[int]]
    output_tokens_mean: float
    calls_mean: float
    duration_ms_mean: float
    correct_by_task: dict[str, list[bool | None]]
    cache: dict[str, int]  # summed over runs, from the SDK transcripts (0s when absent)
    cost_est_usd: float
    reopens: int  # show('out#…') calls, pruning arms only
    pruned_results: int


@dataclass
class Verdict:
    arm: str
    adoptable: bool
    lost_tasks: list[str]  # passed on every baseline pass, failed on every arm pass
    gained_tasks: list[str]
    passes_total: int
    baseline_passes_total: int
    passes_mean: float  # per pass, so arms with different pass counts compare
    baseline_passes_mean: float
    tokens_share: float  # arm mean / baseline mean


@dataclass
class Experiment:
    agent: str
    split: str
    baseline: str
    arms: dict[str, ArmStats] = field(default_factory=dict)
    verdicts: dict[str, Verdict] = field(default_factory=dict)
    recommended: str = ""


def _calls(session_id: str | None) -> list[dict[str, int]]:
    """Per-API-call usage from the CLI transcript, deduplicated by message id."""
    if not session_id:
        return []
    hits = list(TRANSCRIPTS.glob(f"*/{session_id}.jsonl"))
    if not hits:
        return []
    seen: dict[str, dict[str, int]] = {}
    for line in hits[0].read_text().splitlines():
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        if m.get("type") != "assistant":
            continue
        msg = m.get("message", {})
        u = msg.get("usage") or {}
        seen[msg.get("id", str(len(seen)))] = {
            "fresh": int(u.get("input_tokens", 0)),
            "cache_write": int(u.get("cache_creation_input_tokens", 0)),
            "cache_read": int(u.get("cache_read_input_tokens", 0)),
            "output": int(u.get("output_tokens", 0)),
        }
    return list(seen.values())


def _trace_stats(run_dir: Path, task_id: str) -> dict[str, Any]:
    p = run_dir / "traces" / f"{task_id}.json"
    if not p.exists():
        return {"session_id": None, "reopens": 0, "pruned": 0}
    d = json.loads(p.read_text())
    reopens = pruned = 0
    for m in d.get("trace", []):
        if m.get("role") == "assistant":
            for b in m["content"]:
                if b.get("type") == "tool_use" and "show(" in str(b.get("input", {}).get("code")):
                    reopens += 1
        if m.get("role") == "executor":
            pruned = sum(1 for h in m["content"] if "full_output" in h)
    return {"session_id": d.get("session_id"), "reopens": reopens, "pruned": pruned}


def arm_stats(harness: str, metas: list[RunMeta]) -> ArmStats:
    by_task_in: dict[str, list[int]] = defaultdict(list)
    by_task_ok: dict[str, list[bool | None]] = defaultdict(list)
    out_tot = calls_tot = dur_tot = 0
    cache = {k: 0 for k in PRICE}
    reopens = pruned = 0
    n_rows = 0
    passes = []
    for meta in metas:
        _, rows = load_run(meta.run_id)
        passes.append(sum(1 for r in rows if r.correct))
        for r in rows:
            by_task_in[r.task_id].append(r.input_tokens)
            by_task_ok[r.task_id].append(r.correct)
            out_tot += r.output_tokens
            calls_tot += r.n_turns
            dur_tot += r.duration_ms
            n_rows += 1
            ts = _trace_stats(RUNS_DIR / meta.run_id, r.task_id)
            reopens += ts["reopens"]
            pruned += ts["pruned"]
            for c in _calls(ts["session_id"]):
                for k in cache:
                    cache[k] += c[k]
    n = max(n_rows, 1)
    cost = sum(cache[k] * PRICE[k] for k in PRICE) / 1e6
    return ArmStats(
        harness=harness,
        runs=[m.run_id for m in metas],
        n_tasks=len(by_task_in),
        passes_per_run=passes,
        input_tokens_mean=sum(sum(v) for v in by_task_in.values()) / n,
        input_tokens_by_task=dict(by_task_in),
        output_tokens_mean=out_tot / n,
        calls_mean=calls_tot / n,
        duration_ms_mean=dur_tot / n,
        correct_by_task=dict(by_task_ok),
        cache=cache,
        cost_est_usd=round(cost, 4),
        reopens=reopens,
        pruned_results=pruned,
    )


def verdict(base: ArmStats, arm: ArmStats) -> Verdict:
    def solid(a: ArmStats, tid: str) -> bool:
        return bool(a.correct_by_task.get(tid)) and all(a.correct_by_task[tid])

    def never(a: ArmStats, tid: str) -> bool:
        return bool(a.correct_by_task.get(tid)) and not any(a.correct_by_task[tid])

    tasks = sorted(base.correct_by_task, key=int)
    lost = [t for t in tasks if solid(base, t) and never(arm, t)]
    gained = [t for t in tasks if never(base, t) and solid(arm, t)]
    mean_arm = sum(arm.passes_per_run) / max(len(arm.passes_per_run), 1)
    mean_base = sum(base.passes_per_run) / max(len(base.passes_per_run), 1)
    return Verdict(
        arm=arm.harness,
        adoptable=not lost and mean_arm >= mean_base,
        lost_tasks=lost,
        gained_tasks=gained,
        passes_total=sum(arm.passes_per_run),
        baseline_passes_total=sum(base.passes_per_run),
        passes_mean=round(mean_arm, 3),
        baseline_passes_mean=round(mean_base, 3),
        tokens_share=round(arm.input_tokens_mean / max(base.input_tokens_mean, 1), 4),
    )


def compare(
    agent: str = "v2", split: str = "dev", note_prefix: str = "s02 harness experiment"
) -> Experiment:
    """Every eval run of `agent` on `split` whose note starts with `note_prefix`, grouped by harness."""
    groups: dict[str, list[RunMeta]] = defaultdict(list)
    for m in list_runs():
        if (
            m.agent == agent
            and m.split == split
            and m.kind == "eval"
            and m.note.startswith(note_prefix)
        ):
            groups[m.harness].append(m)
    exp = Experiment(agent=agent, split=split, baseline="baseline")
    for h, metas in groups.items():
        exp.arms[h] = arm_stats(h, metas)
    base = exp.arms.get("baseline")
    if base:
        for h, a in exp.arms.items():
            if h != "baseline":
                exp.verdicts[h] = verdict(base, a)
        ok = [v for v in exp.verdicts.values() if v.adoptable]
        if ok:
            exp.recommended = min(ok, key=lambda v: v.tokens_share).arm
    return exp


def write(exp: Experiment) -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(asdict(exp), indent=1) + "\n", encoding="utf-8")
    return OUT


def record_in_ledger(exp: Experiment) -> dict[str, Any]:
    """One ledger entry of kind `harness`: the arms, the verdicts, the adopted profile."""
    from dabstep_loop.loop.ledger import append_entry, next_cycle_number
    from dabstep_loop.tracking.registry import read_registry

    base = exp.arms.get("baseline")
    lines = []
    for h, a in exp.arms.items():
        share = (
            f" · {a.input_tokens_mean / base.input_tokens_mean:.0%} of baseline"
            if base and h != "baseline"
            else ""
        )
        lines.append(
            f"{h}: {a.input_tokens_mean:,.0f} input tokens per question over {len(a.runs)} pass(es), "
            f"passes {a.passes_per_run}, {a.calls_mean:.1f} calls per question{share}"
            + (
                f", {a.reopens} re-opens of {a.pruned_results} pruned outputs"
                if a.pruned_results
                else ""
            )
        )
    for h, v in exp.verdicts.items():
        lines.append(
            f"verdict {h}: {'adoptable' if v.adoptable else 'not adoptable'} — lost {v.lost_tasks or 'none'}, "
            f"gained {v.gained_tasks or 'none'}, mean passes {v.passes_mean} vs {v.baseline_passes_mean}"
        )
    entry = {
        "cycle": next_cycle_number(),
        "kind": "harness",
        "champion": str(read_registry().get("champion", {}).get("agent", exp.agent)),
        "challenger": None,
        "failed": [],
        "summary": (
            f"s02 harness experiment on {exp.agent}/{exp.split}: adopted '{exp.recommended}'"
            if exp.recommended
            else f"s02 harness experiment on {exp.agent}/{exp.split}: nothing adoptable"
        ),
        "notes": lines,
        "runs": {h: a.runs for h, a in exp.arms.items()},
        "recommended": exp.recommended,
        "outcome": {"verdict": "adopt" if exp.recommended else "hold", "harness": exp.recommended},
    }
    append_entry(entry)
    return entry


def read() -> dict[str, Any] | None:
    return json.loads(OUT.read_text()) if OUT.exists() else None


if __name__ == "__main__":  # pragma: no cover
    e = compare()
    print(write(e))
    for h, a in e.arms.items():
        print(
            f"{h:<11} runs={len(a.runs)} in/q={a.input_tokens_mean:>9,.0f} out/q={a.output_tokens_mean:>6,.0f} "
            f"calls={a.calls_mean:.1f} passes={a.passes_per_run} reopens={a.reopens} ${a.cost_est_usd}"
        )
    for h, v in e.verdicts.items():
        print(
            f"  {h}: adoptable={v.adoptable} lost={v.lost_tasks} gained={v.gained_tasks} share={v.tokens_share}"
        )
    print("recommended:", e.recommended, "| cwd", os.getcwd())
