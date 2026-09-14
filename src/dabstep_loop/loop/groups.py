"""Group the 450 by core question: permutations of one template over merchants, months, fees.

The paper says the 450 are permutations of 95 core questions. The template
here is the question with its variable parts blanked — merchant names, months,
years, days, numbers, fee IDs, ACI letters, card schemes, country codes — so
tasks that differ only in those collapse to one key. Reflection uses the
groups to ask whether a solution that passed one member would hold for the
rest; nothing here scores anything.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict

from dabstep_loop.config import context_dir
from dabstep_loop.data.tasks import Task, load_tasks

MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
SCHEMES = "globalcard|nexpay|transactplus|swiftcharge"


def _merchants() -> list[str]:
    p = context_dir() / "merchant_data.json"
    if not p.exists():
        return []
    return [str(m["merchant"]) for m in json.loads(p.read_text())]


def template(question: str, merchants: list[str] | None = None) -> str:
    q = question.lower()
    for m in merchants or _merchants():
        q = q.replace(m.lower(), "<merchant>")
    q = re.sub(rf"\b({MONTHS})\b", "<month>", q)
    q = re.sub(rf"\b({SCHEMES})\b", "<scheme>", q)
    q = re.sub(r"\b(20\d\d)\b", "<year>", q)
    q = re.sub(r"\b\d+(st|nd|rd|th)\b", "<nth>", q)
    q = re.sub(r"\b\d+(\.\d+)?\b", "<n>", q)
    q = re.sub(r"\baci [a-g]\b", "aci <letter>", q)
    q = re.sub(r"= [a-z]\b", "= <letter>", q)
    q = re.sub(r"\b(account type|account_type) [a-z]\b", r"\1 <letter>", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def group_tasks(split: str = "all") -> dict[str, list[Task]]:
    merchants = _merchants()
    groups: dict[str, list[Task]] = defaultdict(list)
    for t in load_tasks(split):
        groups[template(t.question, merchants)].append(t)
    return dict(groups)


def groups_for_dev() -> list[dict[str, object]]:
    """For each dev task: its template, and how many of the 450 share it."""
    merchants = _merchants()
    all_groups = group_tasks("all")
    out: list[dict[str, object]] = []
    for t in load_tasks("dev"):
        key = template(t.question, merchants)
        siblings = [s for s in all_groups.get(key, []) if s.task_id != t.task_id]
        out.append(
            {
                "task_id": t.task_id,
                "level": t.level,
                "template": key,
                "n_siblings": len(siblings),
                "sibling_ids": [s.task_id for s in siblings[:12]],
                "sibling_example": siblings[0].question if siblings else None,
            }
        )
    return out
