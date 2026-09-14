"""The benchmark tasks, as committed JSONL.

`data/tasks/dev.jsonl` is the 10 tasks that ship with answers; `all.jsonl` is the
450 whose answers the leaderboard keeps. Both come straight from the dataset's
`data/tasks/` folder, unmodified, so a row here is a row there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dabstep_loop.config import TASKS_DIR


@dataclass(frozen=True)
class Task:
    task_id: str
    question: str
    guidelines: str
    level: str
    answer: str  # "" on the 450

    @property
    def has_gold(self) -> bool:
        return bool(self.answer.strip())


def _read(path: Path) -> list[Task]:
    tasks: list[Task] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            tasks.append(
                Task(
                    task_id=str(row["task_id"]),
                    question=str(row["question"]),
                    guidelines=str(row.get("guidelines") or ""),
                    level=str(row.get("level") or ""),
                    answer=str(row.get("answer") or ""),
                )
            )
    return tasks


def load_tasks(split: str = "dev") -> list[Task]:
    """`dev` = the 10 with gold; `all` = the 450 without."""
    name = {"dev": "dev.jsonl", "all": "all.jsonl", "default": "all.jsonl"}[split]
    return _read(TASKS_DIR / name)


def task_by_id(task_id: str, split: str = "dev") -> Task:
    for t in load_tasks(split):
        if t.task_id == task_id:
            return t
    raise KeyError(task_id)
