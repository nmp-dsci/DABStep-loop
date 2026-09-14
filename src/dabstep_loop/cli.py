"""`dabstep` — the command line behind every Makefile target."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command()
def data(force: bool = False) -> None:
    """Download the DABstep dataset into data/ and regenerate the committed samples."""
    from dabstep_loop.data.download import download
    from dabstep_loop.data.file_structures import generate

    console.print(download(force=force))
    generate()
    console.print("file_structures.json regenerated")


@app.command()
def eval(  # noqa: A001 - the Makefile target is `eval`
    agent: str = "v0",
    split: str = "dev",
    model: str | None = None,
    workers: int = 2,
    passes: int = 1,
    dry_run: bool = False,
    task: Annotated[list[str] | None, typer.Option("--task", "-t")] = None,
    note: str = "",
    no_track: bool = False,
) -> None:
    """Run an agent version over a split and score it."""
    from dabstep_loop.eval.runner import run_eval

    if split in {"all", "default"} and not dry_run:
        typer.confirm("This scores the 450 — a full leaderboard run. Continue?", abort=True)
    meta, _ = asyncio.run(
        run_eval(agent, split, model, workers, passes, dry_run, task, note, track=not no_track)
    )
    console.print(f"run: runs/{meta.run_id}")


@app.command()
def probe(
    agent: str | None = None,
    k: int = 3,
    seed: int = 0,
    passes: int = 2,
    workers: int = 3,
    model: str | None = None,
    note: str = "",
) -> None:
    """Run a seeded per-family sample of the 450 through an agent, unscored; then compute the signals."""
    from dabstep_loop.eval.runner import run_eval
    from dabstep_loop.loop.sampler import draw
    from dabstep_loop.loop.signals import compute
    from dabstep_loop.tracking.registry import read_registry

    agent = agent or str((read_registry().get("champion") or {}).get("agent") or "v0")
    sample = draw(k=k, seed=seed)
    console.print(
        f"sample: {len(sample.task_ids)} tasks · k={k} seed={seed} · {sample.boundary_first} boundary-first"
    )
    meta, _ = asyncio.run(
        run_eval(
            agent,
            "all",
            model,
            workers,
            passes,
            False,
            sample.task_ids,
            note or f"probe k={k} seed={seed}",
            score=False,
            sample=sample.as_dict(),
        )
    )
    doc = compute(meta.run_id)
    console.print(f"run: runs/{meta.run_id}")
    console.print(json.dumps(doc["composite"]))


@app.command()
def signals(run_id: str) -> None:
    """Recompute the gold-free signals for a run folder (writes signals.json)."""
    from dabstep_loop.loop.signals import compute

    doc = compute(run_id)
    t = Table("family", "n", "S1 modal", "S2 agree", "S3 pass/fail/skip", "S5 format", "turns")
    for fid, b in doc["families"].items():
        t.add_row(
            fid,
            str(b["n"]),
            str(b["s1_modal_share"]),
            str(b["s2_agreement"]),
            f"{b['s3_passed']}/{b['s3_failed']}/{b['s3_skipped']}",
            str(b["s5_compliance"]),
            str(b["turns_mean"]),
        )
    console.print(t)
    console.print(json.dumps(doc["composite"]))


@app.command()
def score(run_id: str) -> None:
    """Re-score a run folder from its results.jsonl."""
    from dabstep_loop.eval.runner import load_run
    from dabstep_loop.eval.score import summarise

    _, results = load_run(run_id)
    console.print(summarise(results))


@app.command()
def runs() -> None:
    """List run folders."""
    from dabstep_loop.eval.runner import list_runs

    t = Table("run", "agent", "model", "split", "pass", "cost")
    for m in list_runs():
        s = m.summary or {}
        p = f"{s.get('passed')}/{s.get('n_scored')}" if s.get("n_scored") else "—"
        t.add_row(m.run_id, m.agent, m.model, m.split, p, f"{s.get('cost_usd', 0):.2f}")
    console.print(t)


@app.command()
def compare(champion: str, challenger: str, alpha: float = 0.05) -> None:
    """Apply the promotion gate between two runs."""
    from dabstep_loop.eval.compare import compare as _compare
    from dabstep_loop.eval.runner import load_run

    _, a = load_run(champion)
    _, b = load_run(challenger)
    console.print(_compare(a, b, alpha=alpha))


@app.command()
def register(run_id: str, alias: str = "challenger") -> None:
    """Register a run's agent version in the registry under an alias."""
    from dabstep_loop.tracking.registry import register as _register

    console.print(_register(run_id, alias))


@app.command()
def promote(run_id: str) -> None:
    """Make a run's agent version the champion (after the gate)."""
    from dabstep_loop.tracking.registry import promote as _promote

    console.print(_promote(run_id))


@app.command()
def submit(run_id: str, out: Path | None = None) -> None:
    """Validate a run's submission.jsonl for the leaderboard form."""
    from dabstep_loop.config import RUNS_DIR
    from dabstep_loop.eval.submission import validate

    path = RUNS_DIR / run_id / "submission.jsonl"
    problems = validate(path, split="all")
    if problems:
        for p in problems:
            console.print(f"[red]✗[/] {p}")
        raise typer.Exit(1)
    if out:
        out.write_bytes(path.read_bytes())
    console.print(f"[green]valid[/]: {out or path}")


@app.command()
def loop(
    cycles: int = 1,
    agent: str | None = None,
    optimiser_model: str = "sonnet",
    split: str = "dev",
    workers: int = 2,
) -> None:
    """Run the error loop: eval → diagnose → new version → eval → gate → ledger."""
    from dabstep_loop.loop.run import run_loop

    asyncio.run(
        run_loop(
            cycles=cycles,
            agent=agent,
            optimiser_model=optimiser_model,
            split=split,
            workers=workers,
        )
    )


@app.command()
def uloop(
    cycles: int = 1,
    agent: str | None = None,
    optimiser_model: str = "sonnet",
    k: int = 3,
    seed: int = 0,
    passes: int = 2,
    workers: int = 3,
) -> None:
    """The unsupervised loop: probe the 450 by family → cards → optimiser → paired eval → gate A → ledger."""
    from dabstep_loop.loop.run import run_uloop

    asyncio.run(run_uloop(cycles, agent, optimiser_model, k, seed, passes, workers))


@app.command()
def reflect(run_id: str | None = None, model: str = "sonnet") -> None:
    """One offline reflection pass over the champion's traces (NVIDIA phase 3, on the smoke set)."""
    from dabstep_loop.loop.reflect import run_reflection

    asyncio.run(run_reflection(run_id=run_id, model=model))


@app.command()
def ureflect(run_id: str, model: str = "sonnet") -> None:
    """Unsupervised reflection over a probe run: writes one card per family to loop/families/."""
    from dabstep_loop.loop.ureflect import run_ureflection

    entry = asyncio.run(run_ureflection(run_id, model=model))
    console.print(
        json.dumps({k: entry[k] for k in ("statuses", "priorities", "tokens", "outcome")}, indent=1)
    )


@app.command()
def annotate(version: str, model: str = "sonnet") -> None:
    """Write agents/<version>/change_log.json from the optimiser's own record (post-hoc)."""
    from dabstep_loop.loop.annotate import annotate as _annotate

    out = asyncio.run(_annotate(version, model=model))
    console.print(f"{len(out['changes'])} changes annotated for {version}")


@app.command()
def families(write: bool = True) -> None:
    """Lens 1: the 450 by operation family; writes loop/families/families.json."""
    from dabstep_loop.loop.families import coverage, write_families_file

    if write:
        write_families_file()
    t = Table("family", "name", "tasks", "templates", "levels", "dev anchor")
    for r in coverage():
        t.add_row(
            r["id"],
            r["name"],
            str(r["tasks"]),
            str(r["templates"]),
            json.dumps(r["levels"]),
            ", ".join(r["dev_anchor"]) or "—",
        )
    console.print(t)


@app.command()
def lenses(model: str = "sonnet", seed: int = 0, k: int = 12) -> None:
    """Lenses 2 and 3: local embeddings + one Sonnet membership pass; writes loop/families/lenses.json."""
    from dabstep_loop.loop.lenses import build_lenses

    doc = asyncio.run(build_lenses(model=model, seed=seed, k=k))
    a = doc["agreement"]
    console.print(
        f"k = {doc['embedding']['k']} · ARI l1/l2 {a['ari']['l1_l2']} · l1/l3 {a['ari']['l1_l3']} · "
        f"l2/l3 {a['ari']['l2_l3']} · boundary {a['boundary_count']}/450 · split {a['split_count']} · "
        f"tokens {doc['tokens']}"
    )


@app.command()
def ledger() -> None:
    """Print the loop ledger."""
    from dabstep_loop.loop.ledger import read_ledger

    for e in read_ledger():
        console.print(json.dumps(e, indent=1)[:2000])


@app.command()
def snapshot() -> None:
    """Export the MLflow experiment to loop/mlflow_snapshot.json for the demo image."""
    from dabstep_loop.tracking.snapshot import write_snapshot

    console.print(write_snapshot())


@app.command()
def demo_pack(run_id: str | None = None) -> None:
    """Record the champion's dev-10 answers and traces as the demo replay pack."""
    from dabstep_loop.serving.demo_pack.build import build_pack

    console.print(build_pack(run_id))


@app.command()
def serve(port: int = 8080, host: str = "127.0.0.1") -> None:
    """Serve the API (and the built frontend, if present)."""
    import uvicorn

    uvicorn.run(
        "dabstep_loop.serving.app:create_app", factory=True, host=host, port=port, workers=1
    )


if __name__ == "__main__":
    app()
