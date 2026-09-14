"""Offline reflection (NVIDIA phase 3), demonstrated on the smoke set.

One read-only session over the champion's dev-10 traces — the passes as well
as the failures — asking what the next optimiser should know: which solutions
passed by luck, which would not survive the sibling permutations among the
450, which gaps are still open. It writes nothing but a ledger entry of kind
`reflect`; the next `make loop` shows that entry to the optimiser through
`render_history()`, which is how a reflection changes a version.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from dabstep_loop.agent.llm import EFFORT, require_live, resolve_model, subscription_env
from dabstep_loop.agent.versions import load_version
from dabstep_loop.config import ROOT, RUNS_DIR
from dabstep_loop.eval.runner import load_run
from dabstep_loop.loop.groups import groups_for_dev
from dabstep_loop.loop.ledger import append_entry, next_cycle_number, render_history
from dabstep_loop.loop.optimiser import condense_trace
from dabstep_loop.tracking.registry import read_registry

MAX_TURNS = 40


def build_prompt(run_id: str) -> str:
    meta, results = load_run(run_id)
    version = load_version(meta.agent)
    groups = {str(g["task_id"]): g for g in groups_for_dev()}
    blocks = []
    for r in results:
        g = groups.get(r.task_id, {})
        blocks.append(
            f"## Task {r.task_id} ({r.level}) — {'PASS' if r.correct else 'FAIL'}\n"
            f"QUESTION: {r.question}\nGOLD: {r.gold}\nAGENT: {r.agent_answer!r} · turns {r.n_turns} · {r.error or ''}\n"
            f"SIBLINGS among the 450 with the same template: {g.get('n_siblings', 0)}"
            + (f" · e.g. {g.get('sibling_example')!r}" if g.get("sibling_example") else "")
            + f"\nTRACE:\n{condense_trace(RUNS_DIR / run_id / 'traces' / f'{r.task_id}.json', limit=5000)}\n"
        )
    return f"""You are reviewing agent `{meta.agent}` of a DABstep benchmark loop after its scored run on the ten dev
tasks (run `{run_id}`). This is an offline reflection: you change nothing. You produce notes the next optimiser will read
before it edits `system.md` or `helper.py`. The 450 leaderboard tasks are permutations of these questions over
other merchants, months and fee rules, so the question for every task — passed or failed — is whether the
solution generalises, not just whether it matched.

Read the traces. You may read the repo (`agents/{meta.agent}/`, `data/context/manual.md`, the data) and run
read-only Python via Bash to check a hypothesis. Do not write or edit any file.

# Ledger so far
{render_history([r.task_id for r in results])}

# The champion's helper (signatures)
{chr(10).join(line for line in (version.helper or "").splitlines() if line.startswith("def "))}

# The ten traces
{chr(10).join(blocks)}

# What to produce
Finish with one fenced ```json block, nothing after it:
{{
  "summary": "two or three sentences: what the champion does well, where it is brittle",
  "notes": ["one actionable note per line for the next optimiser: what to add, change or verify, and why"],
  "passed_by_luck": ["task ids whose passing solution would not hold for their siblings, with a reason"],
  "consistency": ["cases where two tasks sharing a template got different treatment"],
  "open_gaps": ["failures whose root cause is still unexplained"]
}}
"""


async def run_reflection(run_id: str | None = None, model: str = "sonnet") -> dict[str, Any]:
    require_live()
    if run_id is None:
        champ = read_registry().get("champion") or {}
        run_id = str(champ.get("run_id") or "")
    if not run_id:
        raise SystemExit("no champion run to reflect on")
    meta, _ = load_run(run_id)

    async def deny_writes(input_data: Any, tool_use_id: str | None, context: Any) -> Any:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Reflection is read-only.",
            }
        }

    from claude_agent_sdk import HookMatcher

    options = ClaudeAgentOptions(
        model=resolve_model(model),
        effort=EFFORT,
        allowed_tools=["Read", "Bash", "Glob", "Grep"],
        disallowed_tools=["Write", "Edit", "MultiEdit", "NotebookEdit"],
        permission_mode="bypassPermissions",
        max_turns=MAX_TURNS,
        cwd=str(ROOT),
        env=subscription_env(),
        setting_sources=[],
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="Write|Edit|MultiEdit|NotebookEdit", hooks=[deny_writes])
            ]
        },
    )
    prompt = build_prompt(run_id)
    text = ""
    tokens = {"reflect_in": 0, "reflect_out": 0}
    turns = 0
    started = time.time()
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock) and b.text.strip():
                        text = b.text
            elif isinstance(msg, ResultMessage):
                turns = msg.num_turns
                u = msg.usage or {}
                tokens["reflect_in"] = (
                    int(u.get("input_tokens", 0))
                    + int(u.get("cache_read_input_tokens", 0))
                    + int(u.get("cache_creation_input_tokens", 0))
                )
                tokens["reflect_out"] = int(u.get("output_tokens", 0))
                if msg.result and not text:
                    text = msg.result
    m = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S)
    parsed: dict[str, Any] = {}
    if m:
        try:
            parsed = json.loads(m[-1])
        except json.JSONDecodeError:
            parsed = {"summary": text[:2000]}
    else:
        parsed = {"summary": text[:2000]}
    entry: dict[str, Any] = {
        "cycle": next_cycle_number(),
        "kind": "reflect",
        "champion": meta.agent,
        "agent": meta.agent,
        "champion_run": run_id,
        "challenger": None,
        "model": model,
        "summary": parsed.get("summary", ""),
        "notes": parsed.get("notes", []),
        "passed_by_luck": parsed.get("passed_by_luck", []),
        "consistency": parsed.get("consistency", []),
        "open_gaps": parsed.get("open_gaps", []),
        "groups": groups_for_dev(),
        "optimiser": {
            "turns": turns,
            "duration_ms": int((time.time() - started) * 1000),
            "cost_usd_est": None,
            "error": None,
        },
        "tokens": tokens,
        "outcome": {"verdict": "recorded"},
    }
    append_entry(entry)
    try:
        from dabstep_loop.tracking.mlflow_log import log_cycle

        log_cycle(entry)
    except Exception:  # noqa: BLE001
        pass
    return entry
