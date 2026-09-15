"""Harness profiles (s02): the baseline is today's session byte for byte; lean and
lean-prune change only what the session carries, never the agent's files."""

from __future__ import annotations

from pathlib import Path

from dabstep_loop.agent.harness import BASELINE, LEAN, LEAN_PRUNE, harness, harness_env, prune_rule
from dabstep_loop.agent.tools.python_executor import ExecutorState, run_code


def test_profiles_are_named_and_baseline_is_inert() -> None:
    assert harness("baseline") is BASELINE
    assert BASELINE.strict_mcp is False and BASELINE.title_call and BASELINE.prune_cap is None
    assert harness_env(BASELINE) == {} and prune_rule(BASELINE) == ""


def test_lean_drops_inherited_tools_and_the_title_call() -> None:
    assert LEAN.strict_mcp and not LEAN.title_call and LEAN.prune_cap is None
    assert harness_env(LEAN) == {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    assert prune_rule(LEAN) == ""


def test_lean_prune_adds_one_rule_line() -> None:
    assert LEAN_PRUNE.strict_mcp and LEAN_PRUNE.prune_cap == 1500
    rule = prune_rule(LEAN_PRUNE)
    assert "1500" in rule and "show(" in rule and "\n" not in rule


def test_unknown_profile_is_an_error() -> None:
    try:
        harness("fast")
    except ValueError as e:
        assert "lean" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_executor_prunes_by_reference_and_show_reopens() -> None:
    st = ExecutorState(prune_cap=300, prune_head=40)
    out = run_code("print('a'*500 + 'needle' + 'b'*200)", st, 10, Path("."))
    assert out.startswith("a" * 40) and "out#1" in out and "706 chars" in out
    assert st.history[0]["full_output"].count("a") == 500  # the trace keeps everything
    win = run_code("show('out#1', find='needle')", st, 10, Path("."))
    assert "needle" in win and "out#1 · chars" in win and "pruned" not in win
    tail = run_code("show('out#1', start=650)", st, 10, Path("."))
    assert tail.startswith("b" * 56) and "· end]" in tail
    assert "no output" in run_code("show('out#9')", st, 10, Path("."))


def test_executor_without_cap_is_unchanged() -> None:
    st = ExecutorState()
    out = run_code("print('a'*5000)", st, 10, Path("."))
    assert out.startswith("a" * 5000) and "out#" not in out and "show" not in st.namespace
    assert "full_output" not in st.history[0]


def test_verdict_is_per_task_on_every_pass() -> None:
    from dabstep_loop.eval.harness_compare import ArmStats, verdict

    def arm(name: str, ok: dict[str, list[bool]], tokens: float) -> ArmStats:
        return ArmStats(
            name,
            [],
            len(ok),
            [sum(v[i] for v in ok.values()) for i in range(2)],
            tokens,
            {},
            0,
            0,
            0,
            dict(ok),
            {},
            0,
            0,
            0,
        )

    base = arm("baseline", {"5": [True, True], "49": [True, False], "2697": [False, False]}, 100)
    same = arm("lean", {"5": [True, True], "49": [False, True], "2697": [False, False]}, 20)
    v = verdict(base, same)
    assert v.adoptable and v.lost_tasks == [] and v.tokens_share == 0.2
    assert v.passes_mean == v.baseline_passes_mean == 1.5
    lost = arm("lean-prune", {"5": [False, False], "49": [True, True], "2697": [True, True]}, 15)
    v = verdict(base, lost)
    assert not v.adoptable and v.lost_tasks == ["5"] and v.gained_tasks == ["2697"]
