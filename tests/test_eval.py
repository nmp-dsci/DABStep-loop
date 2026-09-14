"""Scoring, the gate, and the submission validator, with no model in the loop."""

import json
from pathlib import Path

from dabstep_loop.data.tasks import load_tasks
from dabstep_loop.eval.compare import compare
from dabstep_loop.eval.score import TaskResult, score_answer, summarise
from dabstep_loop.eval.submission import validate


def _r(tid: str, correct: bool | None, level: str = "hard") -> TaskResult:
    return TaskResult(tid, level, "q", "g", "a", correct)


def test_dev_split_has_ten_gold_and_all_has_none() -> None:
    dev = load_tasks("dev")
    assert len(dev) == 10 and all(t.has_gold for t in dev)
    everything = load_tasks("all")
    assert len(everything) == 450 and not any(t.has_gold for t in everything)


def test_score_answer_uses_gold_only_when_present() -> None:
    dev = {t.task_id: t for t in load_tasks("dev")}
    assert score_answer(dev["5"], "NL") is True
    assert score_answer(dev["1273"], "0.120132") is True
    assert score_answer(dev["1273"], "0.10") is False
    assert score_answer(load_tasks("all")[0], "anything") is None


def test_summarise_counts_by_level() -> None:
    s = summarise([_r("1", True, "easy"), _r("2", False), _r("3", True), _r("4", None)])
    assert (s.n, s.n_scored, s.passed) == (4, 3, 2)
    assert (s.easy_passed, s.easy_n, s.hard_passed, s.hard_n) == (1, 1, 1, 2)
    assert s.failed_ids == ["2"]


def test_gate_is_a_one_sided_mcnemar_test() -> None:
    from dabstep_loop.eval.compare import mcnemar_one_sided

    assert mcnemar_one_sided(0, 0) == 1.0
    assert abs(mcnemar_one_sided(5, 0) - 1 / 32) < 1e-12
    assert abs(mcnemar_one_sided(5, 1) - 7 / 64) < 1e-12
    champ = [_r(str(i), i < 4) for i in range(10)]
    five_fixed = [_r(str(i), i < 9) for i in range(10)]
    assert compare(champ, five_fixed).promote  # b=5, c=0 → p=0.031
    flip = [_r("0", False)] + [_r(str(i), i < 9) for i in range(1, 10)]
    v = compare(champ, flip)  # b=5, c=1 → p=0.109
    assert not v.promote and v.broken == ["0"] and abs(v.p_value - 7 / 64) < 1e-12


def test_gate_holds_on_equal() -> None:
    champ = [_r("1", True), _r("2", False)]
    v = compare(champ, champ)
    assert not v.promote and v.p_value == 1.0


def test_submission_validator(tmp_path: Path) -> None:
    p = tmp_path / "sub.jsonl"
    rows = [
        {"task_id": t.task_id, "agent_answer": "x", "reasoning_trace": ""}
        for t in load_tasks("all")
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows))
    assert validate(p) == []
    rows[0]["agent_answer"] = 1  # type: ignore[assignment]
    p.write_text("\n".join(json.dumps(r) for r in rows[:-1]))
    problems = validate(p)
    assert any("not str" in x for x in problems) and any("missing" in x for x in problems)


def test_gate_a_rules() -> None:
    from dabstep_loop.eval.compare import Verdict, gate_a

    clean = Verdict(False, 9, 9, 10, [], [], 0.5)
    before = {
        "s3_passed": 4,
        "s3_failed": 2,
        "s1_mean": 0.6,
        "s2_mean": 0.9,
        "s5_mean": 0.95,
        "errors": 1,
    }
    better = {**before, "s3_passed": 6, "s3_failed": 1, "errors": 0}
    assert gate_a(clean, before, better).promote
    assert not gate_a(clean, before, dict(before)).promote  # nothing moved
    assert not gate_a(clean, before, {**better, "s5_mean": 0.9}).promote  # format slipped
    assert not gate_a(
        Verdict(False, 9, 9, 10, ["2697"], ["1871"], 0.5), before, better
    ).promote  # broke dev
    s1_only = {**before, "s1_mean": 0.8}
    assert gate_a(clean, before, s1_only).promote
    assert not gate_a(clean, before, {**s1_only, "s3_failed": 3}).promote
