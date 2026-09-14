"""Metamorphic invariants: relations between sibling answers that hold whatever the truth is.

A gold answer says whether one task is right. An invariant says whether two
answers can both be right: a year's fees cannot be less than one of its months,
a "cheapest" scheme cannot also be the "most expensive" for the same value,
the fee ids of a day are among the fee ids of its month. A failed invariant is
a proven bug with no gold needed, and it names the two traces to read.

Every check is a pure function over parsed answers and slots, so it is unit
tested on synthetic answers in both directions before it sees a trace. A check
that cannot run (an answer that does not parse, a sibling that was not
sampled) is reported as `skipped`, never as passed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from dabstep_loop.loop.slots import Slots


@dataclass
class Check:
    family: str
    name: str
    tasks: list[str]
    status: str  # passed | failed | skipped
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass
class Answer:
    task_id: str
    text: str
    slots: Slots
    extra: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# parsers
# --------------------------------------------------------------------------
def as_number(text: str) -> float | None:
    t = text.strip().replace(",", "")
    m = re.fullmatch(r"-?\d+(?:\.\d+)?", t)
    return float(t) if m else None


def as_id_set(text: str) -> set[str] | None:
    t = text.strip().strip("[]")
    if t == "":
        return set()
    parts = [p.strip().strip("'\"") for p in t.split(",")]
    if not all(re.fullmatch(r"\d+", p) for p in parts):
        return None
    return set(parts)


def as_name_set(text: str) -> set[str] | None:
    t = text.strip().strip("[]")
    if t == "":
        return set()
    return {p.strip().strip("'\"") for p in t.split(",") if p.strip()}


def as_choice_cost(text: str) -> tuple[str, float] | None:
    m = re.fullmatch(r"\s*([A-Za-z_]+)\s*:\s*(-?\d+(?:\.\d+)?)\s*", text)
    return (m.group(1), float(m.group(2))) if m else None


def _na(text: str) -> bool:
    return text.strip().lower() == "not applicable"


# --------------------------------------------------------------------------
# per-family checks; each takes the family's answers and returns its checks
# --------------------------------------------------------------------------
def check_f01(answers: list[Answer]) -> list[Check]:
    """ids(day) ⊆ ids(month of that day) ⊆ ids(year), per merchant and year."""
    out: list[Check] = []
    by = {
        (a.slots.merchant, a.slots.year, a.slots.period, a.slots.month, a.slots.day_of_year): a
        for a in answers
    }
    for a in answers:
        s = a.slots
        if s.period == "day":
            month = by.get((s.merchant, s.year, "month", s.month_of_day, None))
            if month:
                out.append(_subset("F01", "ids(day) ⊆ ids(month)", a, month))
            year = by.get((s.merchant, s.year, "year", None, None))
            if year:
                out.append(_subset("F01", "ids(day) ⊆ ids(year)", a, year))
        elif s.period == "month":
            year = by.get((s.merchant, s.year, "year", None, None))
            if year:
                out.append(_subset("F01", "ids(month) ⊆ ids(year)", a, year))
    return out


def _subset(fid: str, name: str, small: Answer, big: Answer) -> Check:
    a, b = as_id_set(small.text), as_id_set(big.text)
    tasks = [small.task_id, big.task_id]
    if a is None or b is None:
        return Check(fid, name, tasks, "skipped", "an answer is not an id list")
    missing = sorted(a - b, key=int)
    if missing:
        return Check(
            fid,
            name,
            tasks,
            "failed",
            f"{len(missing)} ids in the finer period are missing from the coarser: {missing[:8]}",
        )
    return Check(fid, name, tasks, "passed", f"{len(a)} ⊆ {len(b)}")


def check_f03(answers: list[Answer]) -> list[Check]:
    """fees(day) ≤ fees(month of that day) ≤ fees(year); every total ≥ 0."""
    out: list[Check] = []
    by = {
        (a.slots.merchant, a.slots.year, a.slots.period, a.slots.month, a.slots.day_of_year): a
        for a in answers
    }
    for a in answers:
        s = a.slots
        v = as_number(a.text)
        if v is None:
            out.append(
                Check("F03", "total is a number ≥ 0", [a.task_id], "skipped", "not a number")
            )
            continue
        out.append(
            Check(
                "F03",
                "total is a number ≥ 0",
                [a.task_id],
                "passed" if v >= 0 else "failed",
                a.text,
            )
        )
        if s.period == "day":
            month = by.get((s.merchant, s.year, "month", s.month_of_day, None))
            if month:
                out.append(_leq("F03", "fees(day) ≤ fees(month)", a, month))
        if s.period in {"day", "month"}:
            year = by.get((s.merchant, s.year, "year", None, None))
            if year:
                out.append(_leq("F03", f"fees({s.period}) ≤ fees(year)", a, year))
    return out


def _leq(fid: str, name: str, small: Answer, big: Answer, tol: float = 1e-6) -> Check:
    a, b = as_number(small.text), as_number(big.text)
    tasks = [small.task_id, big.task_id]
    if a is None or b is None:
        return Check(fid, name, tasks, "skipped", "an answer is not a number")
    ok = a <= b + tol
    return Check(fid, name, tasks, "passed" if ok else "failed", f"{a} vs {b}")


def check_f04(answers: list[Answer]) -> list[Check]:
    """A month's delta has the sign of the year's and no larger magnitude (same merchant, fee, rate)."""
    out: list[Check] = []
    years = {
        (a.slots.merchant, a.slots.year, a.slots.fee_id, a.slots.new_rate): a
        for a in answers
        if a.slots.period == "year"
    }
    for a in answers:
        s = a.slots
        if s.period != "month":
            continue
        y = years.get((s.merchant, s.year, s.fee_id, s.new_rate))
        if not y:
            continue
        m, v = as_number(a.text), as_number(y.text)
        tasks = [a.task_id, y.task_id]
        if m is None or v is None:
            out.append(
                Check(
                    "F04",
                    "|delta(month)| ≤ |delta(year)|, same sign",
                    tasks,
                    "skipped",
                    "not numbers",
                )
            )
            continue
        same_sign = m == 0 or v == 0 or (m > 0) == (v > 0)
        ok = same_sign and abs(m) <= abs(v) + 1e-9
        out.append(
            Check(
                "F04",
                "|delta(month)| ≤ |delta(year)|, same sign",
                tasks,
                "passed" if ok else "failed",
                f"{m} vs {v}",
            )
        )
    return out


def check_f06(answers: list[Answer]) -> list[Check]:
    """Merchants affected by restricting a fee ⊆ merchants the fee applies to at all (same fee, year)."""
    out: list[Check] = []
    plain = {(a.slots.fee_id, a.slots.year): a for a in answers if a.slots.account_type is None}
    for a in answers:
        s = a.slots
        if s.account_type is None:
            continue
        p = plain.get((s.fee_id, s.year))
        if not p:
            continue
        x, y = as_name_set(a.text), as_name_set(p.text)
        tasks = [a.task_id, p.task_id]
        if x is None or y is None or _na(a.text) or _na(p.text):
            out.append(
                Check(
                    "F06",
                    "affected(restricted) ⊆ affected(fee)",
                    tasks,
                    "skipped",
                    "not name lists",
                )
            )
            continue
        extra = sorted(x - y)
        out.append(
            Check(
                "F06",
                "affected(restricted) ⊆ affected(fee)",
                tasks,
                "failed" if extra else "passed",
                f"extra: {extra}" if extra else f"{len(x)} ⊆ {len(y)}",
            )
        )
    return out


def check_f07(answers: list[Answer]) -> list[Check]:
    """For one scheme and filter set, the average fee is non-decreasing in the transaction value."""
    out: list[Check] = []

    def key(s: Slots) -> tuple[Any, ...]:
        return (s.scheme, s.account_type, s.aci, s.mcc)

    groups: dict[tuple[Any, ...], list[Answer]] = {}
    for a in answers:
        groups.setdefault(key(a.slots), []).append(a)
    for _, g in groups.items():
        pts = [
            (a.slots.value, as_number(a.text), a.task_id) for a in g if a.slots.value is not None
        ]
        pts = sorted(p for p in pts if p[1] is not None)
        for (v1, f1, t1), (v2, f2, t2) in zip(pts, pts[1:], strict=False):
            if v1 == v2:
                continue
            assert f1 is not None and f2 is not None
            out.append(
                Check(
                    "F07",
                    "avg fee non-decreasing in value",
                    [t1, t2],
                    "passed" if f1 <= f2 + 1e-9 else "failed",
                    f"{v1}→{f1}, {v2}→{f2}",
                )
            )
    return out


def check_minmax(fid: str, answers: list[Answer]) -> list[Check]:
    """A 'cheapest' and a 'most expensive' for the same setting name different options; cost(min) ≤ cost(max)."""
    out: list[Check] = []

    def key(s: Slots) -> tuple[Any, ...]:
        return (s.merchant, s.year, s.month, s.value, s.scheme, s.aci)

    mins = {key(a.slots): a for a in answers if a.slots.target == "min"}
    for a in answers:
        if a.slots.target != "max":
            continue
        m = mins.get(key(a.slots))
        if not m or a.extra.get("shape") != m.extra.get("shape"):
            continue
        tasks = [m.task_id, a.task_id]
        if _na(a.text) or _na(m.text):
            out.append(Check(fid, "min ≠ max", tasks, "skipped", "Not Applicable"))
            continue
        cm, cx = as_choice_cost(m.text), as_choice_cost(a.text)
        if cm and cx:
            ok = cm[0] != cx[0] and cm[1] <= cx[1] + 1e-9
            out.append(
                Check(
                    fid,
                    "min ≠ max and cost(min) ≤ cost(max)",
                    tasks,
                    "passed" if ok else "failed",
                    f"{m.text} vs {a.text}",
                )
            )
        else:
            ok = m.text.strip().lower() != a.text.strip().lower()
            out.append(
                Check(
                    fid,
                    "min ≠ max",
                    tasks,
                    "passed" if ok else "failed",
                    f"{m.text!r} vs {a.text!r}",
                )
            )
    return out


def check_f11(answers: list[Answer]) -> list[Check]:
    """A grouped answer is sorted ascending by value, as the guideline demands."""
    out: list[Check] = []
    for a in answers:
        vals = [float(v) for v in re.findall(r":\s*(-?\d+(?:\.\d+)?)", a.text)]
        if len(vals) < 2:
            out.append(
                Check(
                    "F11",
                    "groups sorted ascending",
                    [a.task_id],
                    "skipped",
                    "fewer than two groups parsed",
                )
            )
            continue
        ok = all(x <= y for x, y in zip(vals, vals[1:], strict=False))
        out.append(
            Check(
                "F11",
                "groups sorted ascending",
                [a.task_id],
                "passed" if ok else "failed",
                a.text[:80],
            )
        )
    return out


CHECKS = {
    "F01": check_f01,
    "F03": check_f03,
    "F04": check_f04,
    "F06": check_f06,
    "F07": check_f07,
    "F08": lambda a: check_minmax("F08", a),
    "F09": lambda a: check_minmax("F09", a),
    "F11": check_f11,
}


def run_checks(fid: str, answers: list[Answer]) -> list[Check]:
    fn = CHECKS.get(fid)
    return fn(answers) if fn else []
