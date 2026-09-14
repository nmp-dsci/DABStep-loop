"""The promotion gate: a one-sided exact McNemar test that the challenger beats the champion.

Two runs on the same tasks are paired. Only the discordant pairs carry
information: `b` tasks the challenger fixed, `c` tasks it broke. Under the null
(no real difference) each discordant task is a coin flip, so the one-sided
p-value is P(X ≤ c | n = b + c, p = ½). Promote when p < alpha. With ten tasks
the test is blunt by construction — five fixes and no breaks is the smallest
result that clears 0.05 (p = 1/32) — so the verdict carries b, c and p, not
just a word.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import comb
from typing import Any

from dabstep_loop.eval.score import TaskResult, summarise

ALPHA = 0.05


def mcnemar_one_sided(b: int, c: int) -> float:
    """Exact one-sided p-value that the challenger is better: P(breaks ≤ c | n = b + c, ½)."""
    n = b + c
    if n == 0:
        return 1.0
    return float(sum(comb(n, k) for k in range(c + 1))) / float(2**n)


@dataclass
class Verdict:
    promote: bool
    champion_passed: int
    challenger_passed: int
    n: int
    fixed: list[str] = field(default_factory=list)
    broken: list[str] = field(default_factory=list)
    p_value: float = 1.0
    alpha: float = ALPHA
    reason: str = ""


def compare(
    champion: list[TaskResult], challenger: list[TaskResult], alpha: float = ALPHA
) -> Verdict:
    a = {r.task_id: r for r in champion if r.correct is not None}
    b_ = {r.task_id: r for r in challenger if r.correct is not None}
    common = sorted(set(a) & set(b_), key=int)
    fixed = [t for t in common if not a[t].correct and b_[t].correct]
    broken = [t for t in common if a[t].correct and not b_[t].correct]
    sa, sb = summarise([a[t] for t in common]), summarise([b_[t] for t in common])
    p = mcnemar_one_sided(len(fixed), len(broken))
    promote = p < alpha
    reason = (
        f"McNemar one-sided: fixed {len(fixed)}, broke {len(broken)}, p = {p:.3f} "
        f"{'<' if promote else '≥'} α = {alpha}"
    )
    return Verdict(promote, sa.passed, sb.passed, len(common), fixed, broken, p, alpha, reason)


# --------------------------------------------------------------------------
# Gate A for unsupervised cycles: dev-10 must not break, the paired signals must move
# --------------------------------------------------------------------------
@dataclass
class SignalVerdict:
    promote: bool
    dev_broken: list[str]
    dev_fixed: list[str]
    dev_p_value: float
    before: dict[str, float | int | None]
    after: dict[str, float | int | None]
    reason: str = ""


def _num(x: float | int | None) -> float:
    return float(x) if x is not None else 0.0


def gate_a(dev: Verdict, before: dict[str, Any], after: dict[str, Any]) -> SignalVerdict:
    """Promote when no dev task broke and the gold-free composite improved on the same probe sample.

    Improvement = invariants passed strictly up with failures not up, or method
    consistency (S1) up with invariants not worse; and format compliance (S5) not
    down. The McNemar p on dev-10 is recorded, not required: with one dev failure
    left it cannot clear 0.05 on its own, which is why this gate exists."""
    keys = ("s3_passed", "s3_failed", "s1_mean", "s2_mean", "s5_mean", "errors")
    b = {k: before.get(k) for k in keys}
    a = {k: after.get(k) for k in keys}
    if dev.broken:
        return SignalVerdict(
            False, dev.broken, dev.fixed, dev.p_value, b, a, f"broke dev tasks {dev.broken}"
        )
    s3_up = _num(a["s3_passed"]) > _num(b["s3_passed"]) and _num(a["s3_failed"]) <= _num(
        b["s3_failed"]
    )
    s3_not_worse = _num(a["s3_failed"]) <= _num(b["s3_failed"]) and _num(a["s3_passed"]) >= _num(
        b["s3_passed"]
    )
    s1_up = _num(a["s1_mean"]) > _num(b["s1_mean"])
    s5_ok = _num(a["s5_mean"]) >= _num(b["s5_mean"])
    errors_ok = _num(a["errors"]) <= _num(b["errors"])
    improved = (s3_up or (s1_up and s3_not_worse)) and s5_ok and errors_ok
    parts = [
        f"dev: fixed {len(dev.fixed)}, broke 0, p = {dev.p_value:.3f}",
        f"S3 passed {b['s3_passed']} → {a['s3_passed']}, failed {b['s3_failed']} → {a['s3_failed']}",
        f"S1 {b['s1_mean']} → {a['s1_mean']}",
        f"S2 {b['s2_mean']} → {a['s2_mean']}",
        f"S5 {b['s5_mean']} → {a['s5_mean']}",
        f"errors {b['errors']} → {a['errors']}",
    ]
    reason = ("promote: " if improved else "hold: no paired improvement; ") + " · ".join(parts)
    return SignalVerdict(improved, [], dev.fixed, dev.p_value, b, a, reason)
