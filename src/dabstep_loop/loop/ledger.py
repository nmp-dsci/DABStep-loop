"""The loop's memory: `loop/ledger.jsonl`, one entry per cycle, committed.

Every diagnosis the optimiser makes, every change it proposes and what the gate
then said about it lives here, so the next cycle's optimiser reads what was
tried on a task before proposing it again. An entry is written before the
challenger is evaluated (so a crashed cycle still leaves its reasoning) and the
`outcome` is filled in by the harness after the gate — never by the optimiser.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from dabstep_loop.config import LEDGER_PATH, LOOP_DIR


def read_ledger() -> list[dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def append_entry(entry: dict[str, Any]) -> None:
    LOOP_DIR.mkdir(exist_ok=True)
    entry.setdefault("at", datetime.now(UTC).isoformat())
    with LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def update_entry(cycle: int, kind: str, **fields: Any) -> None:
    """Rewrite the ledger with `fields` merged into the entry for `cycle`/`kind`."""
    entries = read_ledger()
    for e in entries:
        if e.get("cycle") == cycle and e.get("kind", "cycle") == kind:
            e.update(fields)
    LEDGER_PATH.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8"
    )


def next_cycle_number() -> int:
    cycles = [int(e.get("cycle", 0)) for e in read_ledger()]
    return (max(cycles) + 1) if cycles else 1


def prior_attempts(task_id: str) -> list[dict[str, Any]]:
    """Every earlier diagnosis of one task, with the cycle's verdict and whether the task got fixed."""
    out: list[dict[str, Any]] = []
    for e in read_ledger():
        if e.get("kind", "cycle") != "cycle":
            continue
        outcome = e.get("outcome") or {}
        for d in e.get("diagnoses", []):
            if str(d.get("task_id")) != str(task_id):
                continue
            fixed = task_id in (outcome.get("fixed") or [])
            broken = task_id in (outcome.get("broken") or [])
            still_failed = task_id in (outcome.get("still_failed") or [])
            out.append(
                {
                    "cycle": e.get("cycle"),
                    "challenger": e.get("challenger"),
                    "root_cause": d.get("root_cause"),
                    "surface": d.get("surface"),
                    "change": d.get("change"),
                    "verdict": outcome.get("verdict", "pending"),
                    "task_outcome": "fixed"
                    if fixed
                    else "broken"
                    if broken
                    else "still failed"
                    if still_failed
                    else "unknown",
                }
            )
    return out


def render_history(task_ids: list[str]) -> str:
    """The history block for the optimiser prompt: what was tried, and what happened."""
    entries = read_ledger()
    if not entries:
        return "No earlier cycles. This is the first optimisation; there is nothing to avoid repeating yet."
    lines = [
        "Earlier cycles (newest last). Do not repeat a change whose task outcome was 'still failed' or 'broken' unless you explain what is different this time."
    ]
    for e in entries:
        kind = e.get("kind", "cycle")
        o = e.get("outcome") or {}
        if kind == "cycle":
            lines.append(
                f"- cycle {e.get('cycle')}: {e.get('champion')} → {e.get('challenger')} · verdict {o.get('verdict', 'pending')}"
                f" · passes {o.get('passes', '?')} · fixed {o.get('fixed', [])} · broken {o.get('broken', [])}"
            )
            lines.append(f"    prompt: {e.get('prompt_diff_summary', '')}")
            lines.append(f"    helper: {e.get('helper_diff_summary', '')}")
        else:
            lines.append(f"- {kind} {e.get('cycle')}: {e.get('summary', '')[:800]}")
            for n in e.get("notes", [])[:8]:
                lines.append(f"    · {str(n)[:1500]}")
    for tid in task_ids:
        attempts = prior_attempts(tid)
        if attempts:
            lines.append(f"- task {tid} was diagnosed before:")
            for a in attempts:
                lines.append(
                    f"    cycle {a['cycle']} ({a['surface']}): {a['change']} → {a['task_outcome']} (cycle verdict {a['verdict']})"
                )
    return "\n".join(lines)
