"""The leaderboard file: `{"task_id","agent_answer","reasoning_trace"}` per line.

The upload form rejects a file with a missing id, a non-string field or a NaN.
`validate` reproduces those checks so a bad file fails here, not on the Hub.
"""

from __future__ import annotations

import json
from pathlib import Path

from dabstep_loop.data.tasks import load_tasks
from dabstep_loop.eval.score import TaskResult

FIELDS = ("task_id", "agent_answer", "reasoning_trace")


def write_submission(path: Path, results: list[TaskResult], traces: dict[str, str]) -> Path:
    with path.open("w", encoding="utf-8") as f:
        for r in results:
            row = {
                "task_id": str(r.task_id),
                "agent_answer": str(r.agent_answer),
                "reasoning_trace": str(traces.get(r.task_id, "")),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def validate(path: Path, split: str = "all") -> list[str]:
    """Return the problems with a submission file; an empty list means it will upload."""
    problems: list[str] = []
    expected = {t.task_id for t in load_tasks(split)}
    seen: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                problems.append(f"line {n}: not JSON ({e})")
                continue
            for field in FIELDS:
                if field not in row:
                    problems.append(f"line {n}: missing {field}")
                elif not isinstance(row[field], str):
                    problems.append(f"line {n}: {field} is {type(row[field]).__name__}, not str")
                elif row[field].strip().lower() == "nan":
                    problems.append(f"line {n}: {field} is NaN")
            tid = str(row.get("task_id", ""))
            if tid in seen:
                problems.append(f"line {n}: duplicate task_id {tid}")
            seen.add(tid)
    missing = sorted(expected - seen, key=int)
    if missing:
        problems.append(
            f"{len(missing)} task_ids missing: {missing[:10]}{'…' if len(missing) > 10 else ''}"
        )
    extra = sorted(seen - expected)
    if extra:
        problems.append(f"{len(extra)} unexpected task_ids: {extra[:10]}")
    return problems
