"""Scoring a run: the leaderboard's own `question_scorer`, applied per task.

The 450 have no gold, so a score exists only for the dev split; on the 450 this
records answers and leaves `correct` as None.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from dabstep_loop.data.tasks import Task
from dabstep_loop.eval.scorer import question_scorer


@dataclass
class TaskResult:
    task_id: str
    level: str
    question: str
    gold: str
    agent_answer: str
    correct: bool | None
    n_turns: int = 0
    duration_ms: int = 0
    cost_usd: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    terminal_reason: str | None = None


def score_answer(task: Task, agent_answer: str) -> bool | None:
    if not task.has_gold:
        return None
    return bool(question_scorer(agent_answer, task.answer))


@dataclass
class Summary:
    n: int
    n_scored: int
    passed: int
    pass_rate: float | None
    easy_passed: int
    easy_n: int
    hard_passed: int
    hard_n: int
    failed_ids: list[str]
    errored_ids: list[str]
    cost_usd: float
    duration_ms: int


def summarise(results: list[TaskResult]) -> Summary:
    scored = [r for r in results if r.correct is not None]
    passed = [r for r in scored if r.correct]
    easy = [r for r in scored if r.level == "easy"]
    hard = [r for r in scored if r.level == "hard"]
    return Summary(
        n=len(results),
        n_scored=len(scored),
        passed=len(passed),
        pass_rate=(len(passed) / len(scored)) if scored else None,
        easy_passed=sum(1 for r in easy if r.correct),
        easy_n=len(easy),
        hard_passed=sum(1 for r in hard if r.correct),
        hard_n=len(hard),
        failed_ids=[r.task_id for r in scored if not r.correct],
        errored_ids=[r.task_id for r in results if r.error],
        cost_usd=sum(r.cost_usd or 0.0 for r in results),
        duration_ms=sum(r.duration_ms for r in results),
    )


def write_results(path: Path, results: list[TaskResult]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


def read_results(path: Path) -> list[TaskResult]:
    out: list[TaskResult] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(TaskResult(**json.loads(line)))
    return out
