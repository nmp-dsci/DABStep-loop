"""Answer extraction, the version fingerprint, the executor, the prompt — no model."""

from pathlib import Path

from dabstep_loop.agent.answer import extract_agent_answer
from dabstep_loop.agent.llm import BillingError, require_live, resolve_model, subscription_env
from dabstep_loop.agent.tools.python_executor import ExecutorState, run_code
from dabstep_loop.agent.versions import helper_signatures, list_versions, load_version
from dabstep_loop.config import ROOT
from dabstep_loop.loop.groups import template


def test_extract_agent_answer_shapes() -> None:
    assert extract_agent_answer('{"agent_answer": "NL"}') == "NL"
    assert (
        extract_agent_answer('Here it is:\n```json\n{"agent_answer": "0.120132"}\n```')
        == "0.120132"
    )
    assert extract_agent_answer('{"agent_answer": [1, 2, 3]}') == "1, 2, 3"
    assert extract_agent_answer('{"agent_answer": 42}') == "42"
    assert extract_agent_answer("just text") == "just text"
    assert extract_agent_answer("") == ""


def test_versions_have_fingerprints_and_frozen_config() -> None:
    v0 = load_version("v0")
    assert len(v0.fingerprint) == 12 and v0.config.model == "haiku" and v0.config.max_turns == 20
    assert "def load_fees" in helper_signatures(v0.helper or "")
    assert [v.name for v in list_versions()][0] == "v0"


def test_executor_persists_state_and_breaks_loops(tmp_path: Path) -> None:
    state = ExecutorState(helper_path=ROOT / "agents" / "v0" / "helper.py")
    assert "3" in run_code("x = 1 + 2\nx", state, 10, tmp_path)
    assert "6" in run_code("x * 2", state, 10, tmp_path)
    assert "from helper import calculate_fee" and "0.12" in run_code(
        "from helper import calculate_fee\nround(calculate_fee(0.1, 20, 10), 4)",
        state,
        10,
        tmp_path,
    )
    assert "Error (ZeroDivisionError)" in run_code("1/0", state, 10, tmp_path)
    run_code("y = 1", state, 10, tmp_path)
    run_code("y = 1", state, 10, tmp_path)
    assert run_code("y = 1", state, 10, tmp_path).startswith("STOP")
    assert "TimeoutError" in run_code("import time; time.sleep(3)", state, 1, tmp_path)


def test_billing_guard(monkeypatch: "pytest.MonkeyPatch") -> None:  # noqa: F821
    import pytest

    monkeypatch.setenv("DEMO_MODE", "1")
    with pytest.raises(BillingError):
        require_live()
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("BILLING", "subscription")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with pytest.raises(BillingError):
        require_live()
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc")
    env = subscription_env()
    assert env["ANTHROPIC_API_KEY"] == "" and "CLAUDE_CODE_SESSION_ID" not in env
    assert resolve_model("haiku") == "claude-haiku-4-5" and resolve_model("claude-x") == "claude-x"


def test_template_collapses_permutations() -> None:
    a = template(
        "For Belles_cookbook_store in January 2023, what are the fee IDs?",
        ["Belles_cookbook_store", "Crossfit_Hanna"],
    )
    b = template(
        "For Crossfit_Hanna in March 2024, what are the fee IDs?",
        ["Belles_cookbook_store", "Crossfit_Hanna"],
    )
    assert a == b == "for <merchant> in <month> <year>, what are the fee ids?"
