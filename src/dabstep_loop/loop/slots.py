"""The variable parts of a question, parsed: merchant, period, fee id, scheme, value…

`groups.template()` blanks these to find siblings; this module keeps them, so the
sampler can pair a day task with its month and year (F01, F03), a "cheapest"
with its "most expensive" (F08, F09), and the invariants can compare the
answers. Parsing is by regex over the question text and is deliberately
narrow: a slot is None when the question does not state it.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass

from dabstep_loop.data.tasks import Task
from dabstep_loop.loop.groups import _merchants

MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
SCHEMES = ["GlobalCard", "NexPay", "TransactPlus", "SwiftCharge"]


@dataclass(frozen=True)
class Slots:
    merchant: str | None = None
    year: int | None = None
    month: int | None = None  # 1–12
    month_to: int | None = None  # F11 ranges: "between January and April"
    day_of_year: int | None = None
    fee_id: int | None = None
    new_rate: float | None = None
    scheme: str | None = None
    value: float | None = None
    account_type: str | None = None
    aci: str | None = None
    mcc: int | None = None
    target: str | None = None  # "min" | "max"
    group_by: str | None = None

    @property
    def period(self) -> str:
        """day | month | year | none — the finest period the question states."""
        if self.day_of_year is not None:
            return "day"
        if self.month is not None:
            return "month"
        if self.year is not None:
            return "year"
        return "none"

    @property
    def month_of_day(self) -> int | None:
        if self.day_of_year is None:
            return None
        year = self.year or 2023
        return (dt.date(year, 1, 1) + dt.timedelta(days=self.day_of_year - 1)).month


def parse(task: Task, merchants: list[str] | None = None) -> Slots:
    q = task.question
    ql = q.lower()
    merchant = next((m for m in (merchants or _merchants()) if m.lower() in ql), None)
    ym = re.search(r"\b(20\d\d)\b", q)
    year = int(ym.group(1)) if ym else None
    months = [i + 1 for i, m in enumerate(MONTHS) if re.search(rf"\b{m}\b", ql)]
    rng = re.search(r"between (\w+) and (\w+)", ql)
    month = month_to = None
    if rng and rng.group(1) in MONTHS and rng.group(2) in MONTHS:
        month, month_to = MONTHS.index(rng.group(1)) + 1, MONTHS.index(rng.group(2)) + 1
    elif months:
        month = months[0]
    dm = re.search(r"\b(\d+)(?:st|nd|rd|th) of the year\b", ql)
    fm = re.search(r"\bid\s*=?\s*(\d+)\b", ql)
    rm = re.search(r"changed to (\d+(?:\.\d+)?)", ql)
    scheme = next((s for s in SCHEMES if s.lower() in ql), None)
    vm = re.search(r"(?:value of|transaction of) (\d+(?:\.\d+)?) (?:eur|euros)", ql)
    am = re.search(r"account[ _]type\s*(?:=|:)?\s*([a-z])\b", ql)
    acim = re.search(r"\baci\s*(?:=|:)\s*([a-z])\b|\baci ([a-g])\b(?! \w)", ql)
    mm = re.search(r"mcc code to (\d+)", ql)
    target = "min" if re.search(r"\b(cheapest|minimum|lowest)\b", ql) else None
    if re.search(r"\b(most expensive|maximum|highest)\b", ql):
        target = "max"
    gm = re.search(r"grouped by (\w+)", ql)
    return Slots(
        merchant=merchant,
        year=year,
        month=month,
        month_to=month_to,
        day_of_year=int(dm.group(1)) if dm else None,
        fee_id=int(fm.group(1)) if fm else None,
        new_rate=float(rm.group(1)) if rm else None,
        scheme=scheme,
        value=float(vm.group(1)) if vm else None,
        account_type=am.group(1).upper() if am else None,
        aci=(acim.group(1) or acim.group(2)).upper() if acim else None,
        mcc=int(mm.group(1)) if mm else None,
        target=target,
        group_by=gm.group(1) if gm else None,
    )


def as_dict(s: Slots) -> dict[str, object]:
    return {k: v for k, v in asdict(s).items() if v is not None}
