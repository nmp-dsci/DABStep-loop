"""Lens 1: the 450 grouped by *operation*, twelve families over the 106 templates.

`groups.template()` blanks the variable parts of a question (merchant, month,
fee id, scheme…) so permutations collapse to one template. This module maps
each template to a family — the computation the question needs — with an
ordered table of regular expressions. A rule, not an embedding or a model,
because the 450 are literal permutations (the paper says 95 core questions)
and a rule can be cited on a family card. The two other lenses (embeddings,
a Sonnet membership pass) live in `lenses.py` and only say how much to trust
this assignment per task; the family id on every card comes from here.

Nothing here reads a gold answer.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from dabstep_loop.config import LOOP_DIR
from dabstep_loop.data.tasks import Task, load_tasks
from dabstep_loop.loop.groups import _merchants, template

FAMILIES_DIR = LOOP_DIR / "families"


@dataclass(frozen=True)
class Family:
    id: str
    name: str
    pattern: str  # regex over the blanked template; first match in table order wins
    operation: str  # one line: the computation every member needs
    invariant: str  # the gold-free relation between siblings (checked by loop/invariants.py)


# Order matters: the first pattern that matches a template names the family.
# F12 is the catch-all for the easy descriptive questions, so it is last.
FAMILIES: tuple[Family, ...] = (
    Family(
        "F01",
        "fee-ids-for-merchant-period",
        r"(applicable fee ids for <merchant>|fee ids applicable to <merchant>)",
        "the fee rules whose criteria match a merchant's transactions in a day, month or year",
        "ids(day) ⊆ ids(month) ⊆ ids(year) for one merchant",
    ),
    Family(
        "F02",
        "fee-ids-by-attributes",
        r"fee id or ids that apply to account_type",
        "the fee rules whose account_type and aci fields match, wildcards included",
        "rules with both fields null appear in every (account_type, aci) answer",
    ),
    Family(
        "F03",
        "total-fees-paid",
        r"total fees \(in euros\) that <merchant>",
        "sum of fee(rule, transaction) over every matching rule for a merchant in a period",
        "Σ months = year; Σ days of a month = month",
    ),
    Family(
        "F04",
        "delta-fee-rate-change",
        r"delta would <merchant> pay if the relative fee",
        "fees under a rule with its rate replaced, minus fees under the rule as is",
        "delta is linear in (new − old) rate; an unchanged rate gives 0",
    ),
    Family(
        "F05",
        "delta-mcc-change",
        r"changed its mcc code",
        "yearly fees with the merchant's MCC swapped, minus yearly fees as is",
        "the merchant's own MCC gives 0; delta = fees(new) − fees(old), both via F03",
    ),
    Family(
        "F06",
        "merchants-affected-by-fee",
        r"(which merchants would have been affected|which merchants were affected by the fee)",
        "the merchants with at least one transaction matching a rule (or losing it under a change)",
        "affected ⊆ merchants matching the rule today",
    ),
    Family(
        "F07",
        "average-fee-for-scheme",
        r"average fee that the card scheme <scheme> would charge",
        "mean of fee(rule, value) over the scheme's rules that match the stated filters",
        "avg(value) is affine in value; a narrower filter uses a subset of rules",
    ),
    Family(
        "F08",
        "cheapest-or-priciest-choice",
        r"(most expensive authorization|in the average scenario, which card scheme|most expensive mcc)",
        "the same per-option fee table F07 averages, then argmin or argmax over options",
        "the chosen option's cost is ≤ (or ≥) every alternative in the same table; max ≥ mean",
    ),
    Family(
        "F09",
        "steer-traffic-scheme",
        r"steer traffic",
        "a merchant's period fees recomputed per card scheme, then argmin or argmax",
        "min-scheme ≠ max-scheme; per-scheme totals reconcile with F03's total",
    ),
    Family(
        "F10",
        "move-fraud-to-aci",
        r"move the fraudulent transactions towards a different authorization",
        "fees on the merchant's fraudulent transactions recomputed per ACI, then argmin",
        "the chosen ACI's cost is ≤ every alternative in the same table",
    ),
    Family(
        "F11",
        "avg-value-grouped-by",
        r"average transaction value grouped by",
        "mean eur_amount of a merchant's scheme transactions in a month range, per group",
        "the count-weighted mean of the groups equals the ungrouped mean",
    ),
    Family(
        "F12",
        "easy-descriptive",
        r".*",
        "descriptive statistics over payments.csv; format discipline, not fee logic",
        "two runs agree and the answer matches the guideline format",
    ),
)

_FAMILY_BY_ID = {f.id: f for f in FAMILIES}


def family_of_template(tpl: str) -> Family:
    for f in FAMILIES:
        if re.search(f.pattern, tpl):
            return f
    raise ValueError(f"no family for template: {tpl!r}")  # unreachable: F12 is `.*`


def family_of(question: str, merchants: list[str] | None = None) -> Family:
    return family_of_template(template(question, merchants))


def family_by_id(fid: str) -> Family:
    return _FAMILY_BY_ID[fid]


def assign(split: str = "all") -> dict[str, dict[str, Any]]:
    """task_id → {family, template, level, question} for every task in the split."""
    merchants = _merchants()
    out: dict[str, dict[str, Any]] = {}
    for t in load_tasks(split):
        tpl = template(t.question, merchants)
        out[t.task_id] = {
            "family": family_of_template(tpl).id,
            "template": tpl,
            "level": t.level,
            "question": t.question,
        }
    return out


def members(fid: str, split: str = "all") -> list[Task]:
    merchants = _merchants()
    return [t for t in load_tasks(split) if family_of(t.question, merchants).id == fid]


def coverage() -> list[dict[str, Any]]:
    """One row per family: members among the 450, templates, levels, and the dev-10 anchors."""
    merchants = _merchants()
    rows: dict[str, dict[str, Any]] = {
        f.id: {
            **asdict(f),
            "tasks": 0,
            "templates": set(),
            "levels": Counter(),
            "dev_anchor": [],
        }
        for f in FAMILIES
    }
    for t in load_tasks("all"):
        tpl = template(t.question, merchants)
        r = rows[family_of_template(tpl).id]
        r["tasks"] += 1
        r["templates"].add(tpl)
        r["levels"][t.level] += 1
    for t in load_tasks("dev"):
        rows[family_of(t.question, merchants).id]["dev_anchor"].append(t.task_id)
    out: list[dict[str, Any]] = []
    for r in rows.values():
        out.append(
            {
                **{k: v for k, v in r.items() if k not in {"templates", "levels"}},
                "templates": len(r["templates"]),
                "levels": dict(r["levels"]),
            }
        )
    return out


def templates_by_family(split: str = "all") -> dict[str, list[dict[str, Any]]]:
    merchants = _merchants()
    by: dict[str, Counter[str]] = defaultdict(Counter)
    for t in load_tasks(split):
        tpl = template(t.question, merchants)
        by[family_of_template(tpl).id][tpl] += 1
    return {
        fid: [{"template": k, "n": n} for k, n in c.most_common()] for fid, c in sorted(by.items())
    }


def write_families_file() -> dict[str, Any]:
    """`loop/families/families.json`: the table, the coverage and every task's assignment."""
    FAMILIES_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "families": coverage(),
        "templates": templates_by_family("all"),
        "tasks": assign("all"),
    }
    (FAMILIES_DIR / "families.json").write_text(
        json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return doc
