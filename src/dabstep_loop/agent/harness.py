"""Harness profiles: what the SDK session carries besides the agent's two files.

The cost of a question is mostly the harness, not the agent. Measured on the
champion (s02): every API call read a 27k-token prefix of connector tool
schemas the CLI inherits from the user-level claude.ai config, beside our
2.7k of system prompt, task prompt and one tool. A profile names the harness
knobs so a run can say which it used (`run.json.harness`), and two runs of the
same agent under two profiles can be compared for tokens with the answers as
the guard. Nothing here touches `system.md` or `helper.py`, or the fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Harness:
    name: str
    strict_mcp: bool  # only the MCP server we pass; no inherited connector tools
    title_call: bool  # allow the CLI's separate session-title model call
    prune_cap: int | None  # tool output longer than this (chars) is cut to head + a reference
    prune_head: int = 600  # chars kept in place when pruned


BASELINE = Harness("baseline", strict_mcp=False, title_call=True, prune_cap=None)
LEAN = Harness("lean", strict_mcp=True, title_call=False, prune_cap=None)
LEAN_PRUNE = Harness("lean-prune", strict_mcp=True, title_call=False, prune_cap=1500)

HARNESSES: dict[str, Harness] = {h.name: h for h in (BASELINE, LEAN, LEAN_PRUNE)}

# Adopted after the s02 experiment (loop/harness_experiment.json): three passes
# of v2 on dev-10 under `baseline` and `lean` both scored 24/30, with the mean
# input per question 227k → 49k. `lean-prune` re-opened outputs, added a call
# per question and lost three list-answer tasks on one pass; not adopted.
DEFAULT = LEAN

# What the loop's own sessions (optimiser, reflectors, lenses) use: the prefix is
# the same waste there, and none of them answers a dev task.
LOOP_STRICT_MCP = True


def harness(name: str) -> Harness:
    try:
        return HARNESSES[name]
    except KeyError:
        raise ValueError(f"unknown harness {name!r}; one of {sorted(HARNESSES)}") from None


def harness_env(h: Harness) -> dict[str, str]:
    """Environment added to the SDK child for this profile.

    `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` stops the CLI's side calls — the
    session-title Haiku call was measured at ≈ 1.9k tokens per session."""
    return {} if h.title_call else {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}


def prune_rule(h: Harness) -> str:
    """The one task-prompt line a pruning profile adds; empty otherwise."""
    if not h.prune_cap:
        return ""
    return (
        f"Tool output longer than {h.prune_cap} characters is cut to its first "
        f"{h.prune_head} characters plus a reference like [out#3 …]. To read more of it call "
        "show('out#3') for the next window, show('out#3', start=1500) for a later one, or "
        "show('out#3', find='text') to jump to a match. Print only what you need."
    )
