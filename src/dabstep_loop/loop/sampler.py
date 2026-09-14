"""A seeded, stratified sample of the 450 for a probe run.

Per family it draws `k` tasks (boundary tasks from `lenses.json` first, then
the rest, both in seeded order), never a dev-10 id, and then adds the siblings
each family's invariant needs: a day task brings its month and year (F01,
F03), a month delta brings the year delta for the same fee and rate (F04), a
restricted "affected" question brings the plain one (F06), a "cheapest" brings
its "most expensive" (F08, F09). Families whose card is `verified` drop to
k = 1 so a regression still shows. The same seed gives the same sample, which
is what makes a challenger's re-probe a paired comparison.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Any

from dabstep_loop.data.tasks import Task, load_tasks
from dabstep_loop.loop.families import FAMILIES, FAMILIES_DIR, family_of
from dabstep_loop.loop.groups import _merchants, template
from dabstep_loop.loop.lenses import boundary_task_ids
from dabstep_loop.loop.slots import Slots, parse

MAX_SIBLINGS = 2


@dataclass
class Sample:
    seed: int
    k: int
    task_ids: list[str]
    by_family: dict[str, list[str]]  # family → drawn ids (siblings included)
    drawn: dict[str, list[str]]  # family → the k primary draws
    siblings: dict[str, list[str]] = field(default_factory=dict)  # primary id → its siblings
    boundary_first: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "k": self.k,
            "n": len(self.task_ids),
            "by_family": self.by_family,
            "drawn": self.drawn,
            "siblings": self.siblings,
            "boundary_first": self.boundary_first,
        }


def card_status(fid: str) -> str:
    p = FAMILIES_DIR / f"{fid}.json"
    if not p.exists():
        return "open"
    try:
        return str(json.loads(p.read_text(encoding="utf-8")).get("status", "open"))
    except (OSError, ValueError):
        return "open"


def _siblings_for(task: Task, fid: str, pool: list[tuple[Task, Slots]]) -> list[Task]:
    s = parse(task)
    out: list[Task] = []

    def same(o: Slots, *keys: str) -> bool:
        return all(getattr(o, k) == getattr(s, k) for k in keys)

    if fid in {"F01", "F03"} and s.merchant:
        # the coarser periods of the same merchant and year
        wanted = {"day": ["month", "year"], "month": ["year"], "year": []}[s.period]
        for t, o in pool:
            if t.task_id == task.task_id or not same(o, "merchant", "year"):
                continue
            if (
                o.period == "month"
                and "month" in wanted
                and o.month == s.month_of_day
                or o.period == "year"
                and "year" in wanted
            ):
                out.append(t)
    elif fid == "F04" and s.period == "month":
        out += [
            t
            for t, o in pool
            if t.task_id != task.task_id
            and o.period == "year"
            and same(o, "merchant", "year", "fee_id", "new_rate")
        ]
    elif fid == "F06" and s.account_type is not None:
        out += [
            t
            for t, o in pool
            if t.task_id != task.task_id and o.account_type is None and same(o, "fee_id", "year")
        ]
    elif fid in {"F08", "F09"} and s.target:
        other = "max" if s.target == "min" else "min"
        shape = _target_blind(task)
        out += [
            t
            for t, o in pool
            if t.task_id != task.task_id
            and o.target == other
            and same(o, "merchant", "year", "month", "value", "scheme", "aci")
            and _target_blind(t) == shape
        ]
    return out[:MAX_SIBLINGS]


_TARGET_WORDS = re.compile(r"\b(cheapest|most expensive|minimum|maximum|lowest|highest)\b")


def _target_blind(task: Task) -> str:
    """The template with the min/max word blanked, so a 'cheapest' pairs only with its own 'most expensive'."""
    return _TARGET_WORDS.sub("<target>", template(task.question))


def draw(k: int = 3, seed: int = 0, split: str = "all") -> Sample:
    rng = random.Random(seed)
    merchants = _merchants()
    dev_ids = {t.task_id for t in load_tasks("dev")}
    boundary = boundary_task_ids()
    pools: dict[str, list[tuple[Task, Slots]]] = {f.id: [] for f in FAMILIES}
    for t in load_tasks(split):
        if t.task_id in dev_ids:
            continue
        pools[family_of(t.question, merchants).id].append((t, parse(t, merchants)))

    by_family: dict[str, list[str]] = {}
    drawn: dict[str, list[str]] = {}
    siblings: dict[str, list[str]] = {}
    boundary_first = 0
    for f in FAMILIES:
        pool = pools[f.id]
        kk = 1 if card_status(f.id) == "verified" else k
        first = [t for t, _ in pool if t.task_id in boundary]
        rest = [t for t, _ in pool if t.task_id not in boundary]
        rng.shuffle(first)
        rng.shuffle(rest)
        primaries = (first + rest)[:kk]
        boundary_first += sum(1 for t in primaries if t.task_id in boundary)
        chosen: list[str] = []
        for t in primaries:
            chosen.append(t.task_id)
            sibs = _siblings_for(t, f.id, pool)
            siblings[t.task_id] = [x.task_id for x in sibs]
            chosen += [x.task_id for x in sibs]
        drawn[f.id] = [t.task_id for t in primaries]
        by_family[f.id] = list(dict.fromkeys(chosen))
    ids = list(dict.fromkeys(tid for v in by_family.values() for tid in v))
    return Sample(seed, k, sorted(ids, key=int), by_family, drawn, siblings, boundary_first)
