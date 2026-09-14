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


def test_gate_rejects_a_flip_even_with_more_passes() -> None:
    champ = [_r("1", True), _r("2", False), _r("3", False)]
    chall = [_r("1", False), _r("2", True), _r("3", True)]
    v = compare(champ, chall)
    assert not v.promote and v.broken == ["1"] and v.fixed == ["2", "3"]


def test_gate_promotes_strict_improvement() -> None:
    champ = [_r("1", True), _r("2", False)]
    chall = [_r("1", True), _r("2", True)]
    assert compare(champ, chall).promote


def test_gate_holds_on_equal() -> None:
    champ = [_r("1", True), _r("2", False)]
    assert not compare(champ, champ).promote


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
