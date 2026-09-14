"""`make loop`: eval the champion → one optimiser session → eval the challenger → gate → ledger.

Each cycle is one line in `loop/ledger.jsonl`, written before the challenger
runs and completed after the gate. The optimiser never sees the gate's verdict
except through that ledger on the next cycle, which is the point: the record of
what worked is a file it reads, not a memory it keeps.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console

from dabstep_loop.agent.versions import load_version
from dabstep_loop.eval.compare import compare, gate_a
from dabstep_loop.eval.runner import RunMeta, list_runs, load_run, run_eval
from dabstep_loop.eval.score import TaskResult
from dabstep_loop.loop.ledger import append_entry, next_cycle_number, update_entry
from dabstep_loop.loop.optimiser import render_families_block, run_optimiser
from dabstep_loop.tracking.registry import promote, read_registry, register

console = Console()


async def _champion_run(agent: str, split: str, workers: int) -> tuple[RunMeta, list[TaskResult]]:
    """Reuse the registry's run when it is the same bytes on the same split; otherwise re-evaluate."""
    reg = read_registry()
    champ = reg.get("champion") or {}
    version = load_version(agent)
    if (
        champ.get("agent") == agent
        and champ.get("fingerprint") == version.fingerprint
        and champ.get("split") == split
    ):
        try:
            return load_run(str(champ["run_id"]))
        except FileNotFoundError:
            pass
    return await run_eval(agent, split=split, workers=workers, note="champion re-eval for loop")


async def run_cycle(agent: str, optimiser_model: str, split: str, workers: int) -> dict[str, Any]:
    cycle = next_cycle_number()
    champion = load_version(agent)
    champ_meta, champ_results = await _champion_run(agent, split, workers)
    failures = [r for r in champ_results if r.correct is False or r.error]
    console.rule(f"[bold]cycle {cycle}[/] · champion {agent} · {len(failures)} failures")
    if not failures:
        clean: dict[str, Any] = {
            "cycle": cycle,
            "kind": "cycle",
            "champion": agent,
            "challenger": None,
            "failed": [],
            "outcome": {"verdict": "nothing to fix"},
        }
        append_entry(clean)
        return clean

    opt = await run_optimiser(champion, champ_meta.run_id, failures, model=optimiser_model)
    failed_ids = [r.task_id for r in failures]
    opt_tokens = {"optimiser_in": opt.input_tokens, "optimiser_out": opt.output_tokens}
    entry: dict[str, Any] = {
        "cycle": cycle,
        "kind": "cycle",
        "champion": agent,
        "champion_run": champ_meta.run_id,
        "challenger": opt.new_version,
        "optimiser_model": optimiser_model,
        "failed": failed_ids,
        "diagnoses": opt.diagnosis.get("diagnoses", []),
        "prompt_diff_summary": opt.diagnosis.get("prompt_diff_summary", ""),
        "helper_diff_summary": opt.diagnosis.get("helper_diff_summary", ""),
        "expected_to_fix": opt.diagnosis.get("expected_to_fix", []),
        "risks": opt.diagnosis.get("risks", []),
        "optimiser": {
            "turns": opt.n_turns,
            "duration_ms": opt.duration_ms,
            "cost_usd_est": opt.cost_usd,
            "error": opt.error,
        },
        "tokens": opt_tokens,
        "outcome": {"verdict": "pending"},
    }
    append_entry(entry)
    if opt.error and (
        "outside agents" in opt.error or "frozen" in opt.error or "no change" in opt.error
    ):
        update_entry(cycle, "cycle", outcome={"verdict": "rejected", "reason": opt.error})
        console.print(f"[red]cycle {cycle} rejected:[/] {opt.error}")
        return entry

    chall_meta, chall_results = await run_eval(
        opt.new_version, split=split, workers=workers, note=f"loop cycle {cycle} challenger"
    )
    verdict = compare(champ_results, chall_results)
    still_failed = [
        r.task_id for r in chall_results if r.correct is False and r.task_id in failed_ids
    ]
    outcome = {
        "verdict": "promote" if verdict.promote else "hold",
        "reason": verdict.reason,
        "p_value": verdict.p_value,
        "passes": f"{verdict.champion_passed} → {verdict.challenger_passed}",
        "fixed": verdict.fixed,
        "broken": verdict.broken,
        "still_failed": still_failed,
        "challenger_run": chall_meta.run_id,
    }
    eval_tokens = {
        "eval_in": sum(r.input_tokens for r in chall_results),
        "eval_out": sum(r.output_tokens for r in chall_results),
    }
    update_entry(cycle, "cycle", outcome=outcome, tokens={**opt_tokens, **eval_tokens})
    register(chall_meta.run_id, "challenger")
    if verdict.promote:
        promote(chall_meta.run_id)
        console.print(
            f"[green]promoted {opt.new_version}[/]: {outcome['passes']} · fixed {verdict.fixed}"
        )
    else:
        console.print(f"[yellow]hold on {agent}[/]: {verdict.reason} · {outcome['passes']}")
    try:
        from dabstep_loop.tracking.mlflow_log import log_cycle

        log_cycle({**entry, "outcome": outcome})
    except Exception:  # noqa: BLE001
        pass
    entry["outcome"] = outcome
    return entry


async def run_loop(
    cycles: int = 1,
    agent: str | None = None,
    optimiser_model: str = "sonnet",
    split: str = "dev",
    workers: int = 2,
) -> None:
    current = agent or (read_registry().get("champion") or {}).get("agent") or "v0"
    for _ in range(cycles):
        entry = await run_cycle(current, optimiser_model, split, workers)
        outcome = entry.get("outcome") or {}
        if outcome.get("verdict") == "promote":
            current = str(entry["challenger"])
        if outcome.get("verdict") == "nothing to fix":
            break


# --------------------------------------------------------------------------
# the unsupervised cycle: probe → cards → optimiser → paired eval → gate A → ledger
# --------------------------------------------------------------------------
def _find_probe(agent: str, fingerprint: str, k: int, seed: int, passes: int) -> RunMeta | None:
    """The newest finished probe of these exact bytes on this exact sample, if one exists."""
    for m in reversed(list_runs()):
        s = m.sample or {}
        if (
            m.kind == "probe"
            and m.agent == agent
            and m.fingerprint == fingerprint
            and m.passes == passes
            and s.get("k") == k
            and s.get("seed") == seed
            and m.finished_at
        ):
            return m
    return None


async def _probe(
    agent: str,
    k: int,
    seed: int,
    passes: int,
    workers: int,
    note: str,
    task_ids: list[str] | None = None,
) -> tuple[RunMeta, dict[str, Any]]:
    from dabstep_loop.loop.sampler import draw
    from dabstep_loop.loop.signals import compute, read_signals

    version = load_version(agent)
    found = _find_probe(agent, version.fingerprint, k, seed, passes)
    if found is not None:
        console.print(f"[dim]reusing probe {found.run_id}[/]")
        return found, (read_signals(found.run_id) or compute(found.run_id))
    sample = draw(k=k, seed=seed)
    ids = task_ids or sample.task_ids
    meta, _ = await run_eval(
        agent, "all", None, workers, passes, False, ids, note, score=False, sample=sample.as_dict()
    )
    return meta, compute(meta.run_id)


async def run_ucycle(
    agent: str,
    optimiser_model: str,
    k: int = 3,
    seed: int = 0,
    passes: int = 2,
    workers: int = 3,
    reflect_model: str = "sonnet",
) -> dict[str, Any]:
    from dabstep_loop.loop.ureflect import read_cards, run_ureflection

    cycle = next_cycle_number()
    champion = load_version(agent)
    champ_meta, champ_results = await _champion_run(agent, "dev", workers)
    failures = [r for r in champ_results if r.correct is False or r.error]
    console.rule(f"[bold]ucycle {cycle}[/] · champion {agent} · {len(failures)} dev failures")

    probe_meta, before = await _probe(
        agent, k, seed, passes, workers, f"ucycle {cycle} champion probe"
    )
    cards = read_cards()
    stale = not cards or any(c.get("probe_run") != probe_meta.run_id for c in cards.values())
    if stale:
        console.print("[dim]reflecting over the probe → family cards[/]")
        await run_ureflection(probe_meta.run_id, model=reflect_model)
        cycle = next_cycle_number()
    families_block = render_families_block(probe_meta.run_id)

    opt = await run_optimiser(
        champion, champ_meta.run_id, failures, model=optimiser_model, families_block=families_block
    )
    opt_tokens = {"optimiser_in": opt.input_tokens, "optimiser_out": opt.output_tokens}
    entry: dict[str, Any] = {
        "cycle": cycle,
        "kind": "ucycle",
        "champion": agent,
        "champion_run": champ_meta.run_id,
        "champion_probe": probe_meta.run_id,
        "sample": probe_meta.sample,
        "challenger": opt.new_version,
        "optimiser_model": optimiser_model,
        "failed": [r.task_id for r in failures],
        "diagnoses": opt.diagnosis.get("diagnoses", []),
        "prompt_diff_summary": opt.diagnosis.get("prompt_diff_summary", ""),
        "helper_diff_summary": opt.diagnosis.get("helper_diff_summary", ""),
        "expected_to_fix": opt.diagnosis.get("expected_to_fix", []),
        "risks": opt.diagnosis.get("risks", []),
        "signals_before": before.get("composite"),
        "optimiser": {
            "turns": opt.n_turns,
            "duration_ms": opt.duration_ms,
            "cost_usd_est": opt.cost_usd,
            "error": opt.error,
        },
        "tokens": opt_tokens,
        "outcome": {"verdict": "pending"},
    }
    append_entry(entry)
    if opt.error and (
        "outside agents" in opt.error or "frozen" in opt.error or "no change" in opt.error
    ):
        update_entry(cycle, "ucycle", outcome={"verdict": "rejected", "reason": opt.error})
        console.print(f"[red]ucycle {cycle} rejected:[/] {opt.error}")
        return entry

    chall_meta, chall_results = await run_eval(
        opt.new_version, split="dev", workers=workers, note=f"ucycle {cycle} challenger"
    )
    dev = compare(champ_results, chall_results)
    chall_probe, after = await _probe(
        opt.new_version,
        k,
        seed,
        passes,
        workers,
        f"ucycle {cycle} challenger probe",
        probe_meta.task_ids,
    )
    verdict = gate_a(dev, before.get("composite") or {}, after.get("composite") or {})
    outcome = {
        "verdict": "promote" if verdict.promote else "hold",
        "reason": verdict.reason,
        "p_value": dev.p_value,
        "passes": f"{dev.champion_passed} → {dev.challenger_passed}",
        "fixed": dev.fixed,
        "broken": dev.broken,
        "challenger_run": chall_meta.run_id,
        "challenger_probe": chall_probe.run_id,
    }
    eval_tokens = {
        "eval_in": sum(r.input_tokens for r in chall_results),
        "eval_out": sum(r.output_tokens for r in chall_results),
    }
    update_entry(
        cycle,
        "ucycle",
        outcome=outcome,
        signals_after=after.get("composite"),
        signals_by_family={
            fid: {"before": _brief(before, fid), "after": _brief(after, fid)}
            for fid in sorted(set(before.get("families", {})) | set(after.get("families", {})))
        },
        tokens={**opt_tokens, **eval_tokens},
    )
    register(chall_meta.run_id, "challenger")
    if verdict.promote:
        promote(chall_meta.run_id)
        console.print(f"[green]promoted {opt.new_version}[/]: {verdict.reason}")
    else:
        console.print(f"[yellow]hold on {agent}[/]: {verdict.reason}")
    try:
        from dabstep_loop.tracking.mlflow_log import log_cycle

        log_cycle({**entry, "outcome": outcome})
    except Exception:  # noqa: BLE001
        pass
    entry["outcome"] = outcome
    return entry


def _brief(sig: dict[str, Any], fid: str) -> dict[str, Any] | None:
    b = (sig.get("families") or {}).get(fid)
    if not b:
        return None
    return {
        k: b.get(k)
        for k in (
            "n",
            "s1_modal_share",
            "s2_agreement",
            "s3_passed",
            "s3_failed",
            "s5_compliance",
            "turns_mean",
        )
    }


async def run_uloop(
    cycles: int = 1,
    agent: str | None = None,
    optimiser_model: str = "sonnet",
    k: int = 3,
    seed: int = 0,
    passes: int = 2,
    workers: int = 3,
) -> None:
    current = agent or (read_registry().get("champion") or {}).get("agent") or "v0"
    for _ in range(cycles):
        entry = await run_ucycle(current, optimiser_model, k, seed, passes, workers)
        if (entry.get("outcome") or {}).get("verdict") == "promote":
            current = str(entry["challenger"])
