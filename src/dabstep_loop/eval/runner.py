"""`make eval`: run a version over a split, score it, write `runs/<id>/`.

A run folder is the unit everything else reads — the tracker logs it, the gate
compares two of them, the optimiser reads its traces, the viewer lists them.
Nothing is kept only in MLflow.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from dabstep_loop.agent.llm import resolve_model, short_model
from dabstep_loop.agent.session import Solve, save_trace, solve_task
from dabstep_loop.agent.versions import AgentVersion, load_version
from dabstep_loop.config import RUNS_DIR, settings
from dabstep_loop.data.tasks import Task, load_tasks
from dabstep_loop.eval.score import (
    Summary,
    TaskResult,
    read_results,
    score_answer,
    summarise,
    write_results,
)
from dabstep_loop.eval.submission import write_submission

console = Console()


@dataclass
class RunMeta:
    run_id: str
    agent: str
    fingerprint: str
    model: str
    split: str
    n_tasks: int
    workers: int
    passes: int
    dry_run: bool
    started_at: str
    finished_at: str | None = None
    code_sha: str = "unknown"
    summary: dict[str, Any] | None = None
    mlflow_run_id: str | None = None
    note: str = ""
    task_ids: list[str] = field(default_factory=list)


def new_run_id(version: AgentVersion, model: str, split: str) -> str:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{version.name}_{split}_{short_model(model)}"


def _vote(answers: list[str]) -> str:
    """Majority vote across passes; ties go to the first seen (NVIDIA `--passes`)."""
    counts: dict[str, int] = {}
    for a in answers:
        counts[a] = counts.get(a, 0) + 1
    return max(counts, key=lambda k: (counts[k], -answers.index(k)))


async def _solve_with_passes(
    version: AgentVersion, task: Task, model: str, passes: int, run_dir: Path, dry_run: bool
) -> tuple[TaskResult, Solve | None]:
    if dry_run:
        r = TaskResult(
            task.task_id,
            task.level,
            task.question,
            task.answer,
            "dry-run",
            score_answer(task, "dry-run"),
        )
        return r, None
    solves: list[Solve] = []
    for p in range(passes):
        s = await solve_task(version, task, model=model)
        solves.append(s)
        save_trace(
            run_dir
            / "traces"
            / (f"{task.task_id}.json" if passes == 1 else f"{task.task_id}_p{p + 1}.json"),
            s,
        )
    answer = _vote([s.agent_answer for s in solves]) if passes > 1 else solves[0].agent_answer
    best = solves[0]
    r = TaskResult(
        task_id=task.task_id,
        level=task.level,
        question=task.question,
        gold=task.answer,
        agent_answer=answer,
        correct=score_answer(task, answer),
        n_turns=sum(s.n_turns for s in solves),
        duration_ms=sum(s.duration_ms for s in solves),
        cost_usd=sum((s.cost_usd or 0.0) for s in solves)
        if any(s.cost_usd for s in solves)
        else None,
        input_tokens=sum(s.input_tokens for s in solves),
        output_tokens=sum(s.output_tokens for s in solves),
        error="; ".join(s.error for s in solves if s.error) or None,
        terminal_reason=best.terminal_reason,
    )
    return r, best


async def run_eval(
    agent: str,
    split: str = "dev",
    model: str | None = None,
    workers: int = 2,
    passes: int = 1,
    dry_run: bool = False,
    task_ids: list[str] | None = None,
    note: str = "",
    track: bool = True,
) -> tuple[RunMeta, list[TaskResult]]:
    version = load_version(agent)
    model_id = resolve_model(model or version.config.model)
    tasks = load_tasks(split)
    if task_ids:
        wanted = set(task_ids)
        tasks = [t for t in tasks if t.task_id in wanted]
    run_id = new_run_id(version, model_id, split)
    run_dir = RUNS_DIR / run_id
    (run_dir / "traces").mkdir(parents=True, exist_ok=True)
    meta = RunMeta(
        run_id=run_id,
        agent=version.name,
        fingerprint=version.fingerprint,
        model=model_id,
        split=split,
        n_tasks=len(tasks),
        workers=workers,
        passes=passes,
        dry_run=dry_run,
        started_at=datetime.now(UTC).isoformat(),
        code_sha=settings().code_sha,
        note=note,
        task_ids=[t.task_id for t in tasks],
    )
    _write_meta(run_dir, meta)
    for name, text in version.files().items():
        (run_dir / "agent").mkdir(exist_ok=True)
        (run_dir / "agent" / name).write_text(text)

    console.rule(f"[bold]{run_id}[/] · {len(tasks)} tasks · {model_id} · workers={workers}")
    sem = asyncio.Semaphore(max(1, workers))
    results: dict[str, TaskResult] = {}
    traces_text: dict[str, str] = {}

    async def one(task: Task) -> None:
        async with sem:
            t0 = time.time()
            r, s = await _solve_with_passes(version, task, model_id, passes, run_dir, dry_run)
            results[task.task_id] = r
            if s is not None:
                traces_text[task.task_id] = s.final_text
            mark = {True: "[green]pass[/]", False: "[red]FAIL[/]", None: "[dim]—[/]"}[r.correct]
            console.print(
                f"  {task.task_id:>5} {task.level:<4} {mark}  {r.agent_answer[:60]!r}"
                + (f"  gold={task.answer[:40]!r}" if task.has_gold and not r.correct else "")
                + f"  ({time.time() - t0:.0f}s, {r.n_turns} turns)"
                + (f"  [red]{r.error}[/]" if r.error else "")
            )
            # Persist incrementally so a killed run still has its finished tasks.
            write_results(
                run_dir / "results.jsonl",
                [results[t.task_id] for t in tasks if t.task_id in results],
            )

    await asyncio.gather(*(one(t) for t in tasks))
    ordered = [results[t.task_id] for t in tasks]
    write_results(run_dir / "results.jsonl", ordered)
    write_submission(run_dir / "submission.jsonl", ordered, traces_text)
    summary = summarise(ordered)
    meta.finished_at = datetime.now(UTC).isoformat()
    meta.summary = asdict(summary)
    _write_meta(run_dir, meta)
    _print_summary(summary)
    if track and not dry_run:
        try:
            from dabstep_loop.tracking.mlflow_log import log_run

            meta.mlflow_run_id = log_run(run_dir, meta, ordered)
            _write_meta(run_dir, meta)
        except Exception as e:  # noqa: BLE001 - tracking down never fails an eval
            console.print(f"[yellow]mlflow: not logged ({type(e).__name__}: {e})[/]")
    return meta, ordered


def _print_summary(s: Summary) -> None:
    if s.pass_rate is None:
        console.print(f"[bold]{s.n} answered[/], no gold on this split (score at the leaderboard)")
        return
    console.print(
        f"[bold]{s.passed}/{s.n_scored} pass[/] ({s.pass_rate:.0%})  easy {s.easy_passed}/{s.easy_n}  "
        f"hard {s.hard_passed}/{s.hard_n}  failed={s.failed_ids}  errors={s.errored_ids}"
    )


def _write_meta(run_dir: Path, meta: RunMeta) -> None:
    (run_dir / "run.json").write_text(json.dumps(asdict(meta), indent=2) + "\n")


def load_run(run_id: str) -> tuple[RunMeta, list[TaskResult]]:
    run_dir = RUNS_DIR / run_id
    meta = RunMeta(**json.loads((run_dir / "run.json").read_text()))
    results = (
        read_results(run_dir / "results.jsonl") if (run_dir / "results.jsonl").exists() else []
    )
    return meta, results


def list_runs() -> list[RunMeta]:
    metas: list[RunMeta] = []
    if not RUNS_DIR.exists():
        return metas
    for d in sorted(RUNS_DIR.iterdir()):
        if (d / "run.json").exists():
            metas.append(RunMeta(**json.loads((d / "run.json").read_text())))
    return metas
