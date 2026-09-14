"""The promotion gate: a challenger replaces the champion only if nothing regressed.

Two conditions, both required: pass rate at least the champion's, and no task
that the champion passed now fails. "Passes more overall" is not enough — a
version that fixes three and breaks one has learnt something wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dabstep_loop.eval.score import TaskResult, summarise


@dataclass
class Verdict:
    promote: bool
    champion_passed: int
    challenger_passed: int
    n: int
    fixed: list[str] = field(default_factory=list)
    broken: list[str] = field(default_factory=list)
    reason: str = ""


def compare(champion: list[TaskResult], challenger: list[TaskResult]) -> Verdict:
    a = {r.task_id: r for r in champion if r.correct is not None}
    b = {r.task_id: r for r in challenger if r.correct is not None}
    common = sorted(set(a) & set(b), key=int)
    fixed = [t for t in common if not a[t].correct and b[t].correct]
    broken = [t for t in common if a[t].correct and not b[t].correct]
    sa, sb = summarise([a[t] for t in common]), summarise([b[t] for t in common])
    if broken:
        return Verdict(False, sa.passed, sb.passed, len(common), fixed, broken, f"broke {broken}")
    if sb.passed < sa.passed:
        return Verdict(False, sa.passed, sb.passed, len(common), fixed, broken, "fewer passes")
    if sb.passed == sa.passed:
        return Verdict(False, sa.passed, sb.passed, len(common), fixed, broken, "no improvement")
    return Verdict(True, sa.passed, sb.passed, len(common), fixed, broken, f"fixed {fixed}")
