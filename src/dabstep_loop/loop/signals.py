"""Gold-free signals over a probe run, per family: S1 method, S2 agreement, S3 invariants, S5 format.

Everything here is computed from the run folder alone — the traces, the
answers, the questions — and nothing reads a gold answer or the leaderboard.
`signals.json` is written next to the run and copied into the ledger, so a
challenger re-probed on the same sample gives a paired before/after.

S4, the heavy-model audit, is `ureflect.py`; it reads this file.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dabstep_loop.config import RUNS_DIR
from dabstep_loop.data.tasks import Task, load_tasks
from dabstep_loop.eval.runner import RunMeta, load_run
from dabstep_loop.eval.scorer import question_scorer
from dabstep_loop.loop.families import FAMILIES, family_of
from dabstep_loop.loop.groups import _merchants, template
from dabstep_loop.loop.invariants import Answer, Check, run_checks
from dabstep_loop.loop.slots import parse

SCHEMES = {"globalcard", "nexpay", "transactplus", "swiftcharge"}
_TARGET_WORDS = re.compile(r"\b(cheapest|most expensive|minimum|maximum|lowest|highest)\b")


# --------------------------------------------------------------------------
# S1: the method a trace used
# --------------------------------------------------------------------------
def helper_names(helper_source: str) -> set[str]:
    """The public functions a version's helper.py defines."""
    return {n for n in re.findall(r"^def (\w+)\s*\(", helper_source, re.M) if not n.startswith("_")}


def method_signature(
    trace: list[dict[str, Any]], helpers: set[str] | None = None
) -> tuple[str, ...]:
    """The helper functions called plus a few pandas operations, as a sorted tuple.

    Calls are matched both as `helper.name(` and bare `name(` (the agent usually
    does `from helper import *`), so `helpers` is the set of names in that
    version's helper.py."""
    calls: set[str] = set()
    # loaders and lookups are plumbing every trace shares; they are not the method
    names = {n for n in (helpers or set()) if not re.match(r"(load_|get_|day_of_year)", n)}
    for e in trace:
        if e.get("role") != "assistant":
            continue
        content = str(e.get("content", ""))
        for name in re.findall(r"helper\.(\w+)\s*\(", content):
            if not re.match(r"(load_|get_|day_of_year)", name):
                calls.add(f"helper.{name}")
        for name in names:
            if re.search(rf"(?<![\w.]){name}\s*\(", content):
                calls.add(f"helper.{name}")
        if re.search(r"from helper import|import helper", content):
            calls.add("helper:import")
        for op in ("groupby", "merge", "apply(", "iterrows", "json.load", "read_csv"):
            if op in content:
                calls.add(f"pd:{op.rstrip('(')}")
    return tuple(sorted(calls))


def _read_trace(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _pass_traces(run_dir: Path, task_id: str, passes: int) -> list[dict[str, Any]]:
    if passes <= 1:
        p = run_dir / "traces" / f"{task_id}.json"
        return [_read_trace(p)] if p.exists() else []
    out = []
    for i in range(1, passes + 1):
        p = run_dir / "traces" / f"{task_id}_p{i}.json"
        if p.exists():
            out.append(_read_trace(p))
    return out


# --------------------------------------------------------------------------
# S5: the guideline's format
# --------------------------------------------------------------------------
def format_of(guidelines: str) -> str:
    g = guidelines.lower()
    if "comma separated list" in g:
        return "list"
    if "broken down by grouping" in g:
        return "grouped"
    if "selected card scheme and the associated cost" in g:
        return "scheme:cost"
    if "selected aci" in g:
        return "aci:cost"
    if "just one letter" in g:
        return "letter"
    if "name of the card scheme" in g:
        return "scheme"
    if "name of the merchant" in g:
        return "merchant"
    if "yes or no" in g:
        return "yes/no"
    if "in the form 'x. y'" in g:
        return "option"
    if "hour of the day" in g:
        return "hour"
    if "country code" in g:
        return "country"
    if "device category" in g:
        return "text"
    if "number" in g or "percentage" in g:
        return "number"
    return "text"


def format_ok(fmt: str, answer: str, merchants: list[str]) -> bool:
    a = answer.strip()
    if a.lower() == "not applicable":
        return True
    if fmt == "list":
        return a == "" or all(p.strip() for p in a.strip("[]").split(","))
    if fmt == "grouped":
        return bool(re.search(r"\w+\s*:\s*-?\d+(\.\d+)?", a))
    if fmt == "scheme:cost":
        m = re.fullmatch(r"(\w+)\s*:\s*-?\d+(\.\d+)?", a)
        return m is not None and m.group(1).lower() in SCHEMES
    if fmt == "aci:cost":
        return bool(re.fullmatch(r"[A-G]\s*:\s*-?\d+(\.\d+)?", a))
    if fmt == "letter":
        return bool(re.fullmatch(r"[A-Za-z]", a))
    if fmt == "scheme":
        return a.lower() in SCHEMES
    if fmt == "merchant":
        return a in merchants
    if fmt == "yes/no":
        return a.lower() in {"yes", "no"}
    if fmt == "hour":
        return bool(re.fullmatch(r"\d{1,2}", a)) and 0 <= int(a) <= 23
    if fmt == "country":
        return bool(re.fullmatch(r"[A-Z]{2}", a))
    if fmt == "option":
        return bool(re.fullmatch(r"[A-D]\.\s*\S+", a))
    if fmt == "number":
        return bool(re.fullmatch(r"-?\d+(\.\d+)?%?", a.replace(",", "")))
    return a != ""


# --------------------------------------------------------------------------
# the per-family block
# --------------------------------------------------------------------------
@dataclass
class FamilySignals:
    family: str
    n: int
    task_ids: list[str]
    s1_modal_share: float | None
    s1_methods: list[dict[str, Any]]
    s2_agreement: float | None
    s2_disagree: list[str]
    s3_checks: list[dict[str, Any]]
    s3_passed: int
    s3_failed: int
    s3_skipped: int
    s5_compliance: float | None
    s5_bad: list[str]
    turns_mean: float
    errors: list[str]
    answers: dict[str, str] = field(default_factory=dict)


def compute(run_id: str) -> dict[str, Any]:
    meta, results = load_run(run_id)
    run_dir = RUNS_DIR / run_id
    merchants = _merchants()
    helper_path = run_dir / "agent" / "helper.py"
    helpers = (
        helper_names(helper_path.read_text(encoding="utf-8")) if helper_path.exists() else set()
    )
    tasks: dict[str, Task] = {t.task_id: t for t in load_tasks("all")}
    tasks.update({t.task_id: t for t in load_tasks("dev")})
    by_family: dict[str, list[Any]] = defaultdict(list)
    for r in results:
        t = tasks.get(r.task_id)
        if t is None:
            continue
        by_family[family_of(t.question, merchants).id].append((t, r))

    blocks: dict[str, dict[str, Any]] = {}
    for f in FAMILIES:
        rows = by_family.get(f.id, [])
        if not rows:
            continue
        # S1
        sigs: dict[str, tuple[str, ...]] = {}
        turns: list[int] = []
        pass_answers: dict[str, list[str]] = {}
        for t, r in rows:
            traces = _pass_traces(run_dir, t.task_id, meta.passes)
            if traces:
                sigs[t.task_id] = method_signature(traces[0].get("trace", []), helpers)
                pass_answers[t.task_id] = [str(x.get("agent_answer", "")) for x in traces]
            turns.append(r.n_turns)
        counts = Counter(sigs.values())
        modal = counts.most_common(1)[0][0] if counts else None
        s1 = (counts[modal] / len(sigs)) if sigs and modal is not None else None
        methods = [
            {"signature": list(sig), "n": n, "tasks": [tid for tid, s in sigs.items() if s == sig]}
            for sig, n in counts.most_common()
        ]
        # S2
        agree: list[bool] = []
        disagree: list[str] = []
        if meta.passes > 1:
            for tid, ans in pass_answers.items():
                if len(ans) < 2:
                    continue
                ok = all(question_scorer(ans[0], a) for a in ans[1:])
                agree.append(ok)
                if not ok:
                    disagree.append(tid)
        s2 = (sum(agree) / len(agree)) if agree else None
        # S3
        answers = [
            Answer(
                t.task_id,
                r.agent_answer,
                parse(t, merchants),
                {"shape": _TARGET_WORDS.sub("<target>", template(t.question, merchants))},
            )
            for t, r in rows
        ]
        checks: list[Check] = run_checks(f.id, answers)
        # S5
        fmt_ok = [
            (t.task_id, format_ok(format_of(t.guidelines), r.agent_answer, merchants))
            for t, r in rows
        ]
        s5 = sum(1 for _, ok in fmt_ok if ok) / len(fmt_ok)
        blocks[f.id] = asdict(
            FamilySignals(
                family=f.id,
                n=len(rows),
                task_ids=[t.task_id for t, _ in rows],
                s1_modal_share=round(s1, 3) if s1 is not None else None,
                s1_methods=methods,
                s2_agreement=round(s2, 3) if s2 is not None else None,
                s2_disagree=disagree,
                s3_checks=[c.as_dict() for c in checks],
                s3_passed=sum(1 for c in checks if c.status == "passed"),
                s3_failed=sum(1 for c in checks if c.status == "failed"),
                s3_skipped=sum(1 for c in checks if c.status == "skipped"),
                s5_compliance=round(s5, 3),
                s5_bad=[tid for tid, ok in fmt_ok if not ok],
                turns_mean=round(sum(turns) / len(turns), 1) if turns else 0.0,
                errors=[t.task_id for t, r in rows if r.error],
                answers={t.task_id: r.agent_answer for t, r in rows},
            )
        )
    doc = {
        "run_id": run_id,
        "agent": meta.agent,
        "passes": meta.passes,
        "families": blocks,
        "composite": composite(blocks),
    }
    (run_dir / "signals.json").write_text(
        json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return doc


def composite(blocks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The numbers the gate compares: invariants passed/failed, mean S1, S2, S5 over families."""

    def mean(key: str) -> float | None:
        vals = [b[key] for b in blocks.values() if b.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    return {
        "families": len(blocks),
        "tasks": sum(b["n"] for b in blocks.values()),
        "s3_passed": sum(b["s3_passed"] for b in blocks.values()),
        "s3_failed": sum(b["s3_failed"] for b in blocks.values()),
        "s3_skipped": sum(b["s3_skipped"] for b in blocks.values()),
        "s1_mean": mean("s1_modal_share"),
        "s2_mean": mean("s2_agreement"),
        "s5_mean": mean("s5_compliance"),
        "errors": sum(len(b["errors"]) for b in blocks.values()),
    }


def read_signals(run_id: str) -> dict[str, Any] | None:
    p = RUNS_DIR / run_id / "signals.json"
    return dict(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None


def meta_of(run_id: str) -> RunMeta:
    return load_run(run_id)[0]
