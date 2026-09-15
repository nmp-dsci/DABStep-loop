"""Post-hoc change log for a version the optimiser wrote before the log was part of its contract.

A read-only session reads the version's diff against its parent, its
`diagnosis.json` and its own `optimiser_transcript.json`, and writes
`change_log.json`: one entry per edit with what it does and the evidence in the
transcript for why. It is labelled `source: post-hoc` so the page can say so;
versions written after the contract change carry the log inside
`diagnosis.json` with `source: in-session`.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    TextBlock,
)

from dabstep_loop.agent.harness import LOOP_STRICT_MCP
from dabstep_loop.agent.llm import EFFORT, require_live, resolve_model, subscription_env
from dabstep_loop.agent.versions import load_version
from dabstep_loop.config import AGENTS_DIR, ROOT
from dabstep_loop.loop.ledger import read_ledger


def parent_of(name: str) -> str | None:
    for e in read_ledger():
        if e.get("challenger") == name:
            return str(e.get("champion"))
    return None


def unified(a: str, b: str, name: str, parent: str, child: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            a.splitlines(),
            b.splitlines(),
            fromfile=f"{parent}/{name}",
            tofile=f"{child}/{name}",
            lineterm="",
            n=2,
        )
    )


async def annotate(name: str, model: str = "sonnet") -> dict[str, Any]:
    require_live()
    parent = parent_of(name)
    if not parent:
        raise SystemExit(f"{name} was not produced by a loop cycle; nothing to annotate")
    va, vb = load_version(parent), load_version(name)
    fa, fb = va.files(), vb.files()
    diffs = "\n\n".join(
        unified(fa.get(n, ""), fb.get(n, ""), n, parent, name) for n in ("system.md", "helper.py")
    )
    diag = (
        (vb.path / "diagnosis.json").read_text() if (vb.path / "diagnosis.json").exists() else "{}"
    )
    transcript = (
        json.loads((vb.path / "optimiser_transcript.json").read_text())
        if (vb.path / "optimiser_transcript.json").exists()
        else []
    )
    prose = "\n\n".join(m["content"] for m in transcript if m.get("role") == "assistant")
    tools = "\n".join(
        f"- {m['name']}: {str(m['input'].get('command') or m['input'].get('file_path') or '')[:300]}"
        for m in transcript
        if m.get("role") == "tool_use"
    )
    prompt = f"""You are annotating a change already made by an optimiser session in a benchmark loop. The optimiser turned
`agents/{parent}/` into `agents/{name}/` (two files: system.md, helper.py). You must not change any file. Produce a
change log: one entry per distinct edit in the diff below (an added or removed function, a rewritten rule, a
reworded paragraph), with what it does and the evidence in the optimiser's own record for why it was made.
Use only what the record supports: its diagnosis.json, its transcript prose, the commands it ran. Where the record
does not say why, write "not stated in the transcript" — do not invent a reason.

# The diff ({parent} → {name})
{diffs}

# The optimiser's diagnosis.json
{diag}

# The optimiser's prose during the session
{prose}

# The commands the optimiser ran (for evidence of verification)
{tools}

Finish with one fenced ```json block and nothing after it:
{{"changes": [{{"file": "system.md|helper.py", "anchor": "function name or the first five words of the edited block, exactly as in the diff",
  "what": "one sentence", "why": "the evidence, citing the diagnosis task or the transcript", "task_ids": ["…"]}}]}}
Every hunk in the diff must be covered by at least one entry."""

    async def deny(input_data: Any, tool_use_id: str | None, context: Any) -> Any:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "read-only",
            }
        }

    options = ClaudeAgentOptions(
        strict_mcp_config=LOOP_STRICT_MCP,  # no inherited connector tools (s02)
        model=resolve_model(model),
        effort=EFFORT,
        allowed_tools=["Read", "Grep"],
        disallowed_tools=["Write", "Edit", "MultiEdit", "Bash", "NotebookEdit"],
        permission_mode="bypassPermissions",
        max_turns=12,
        cwd=str(ROOT),
        env=subscription_env(),
        setting_sources=[],
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="Write|Edit|MultiEdit|Bash|NotebookEdit", hooks=[deny])
            ]
        },
    )
    text = ""
    tokens = {"in": 0, "out": 0}
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock) and b.text.strip():
                        text = b.text
            elif isinstance(msg, ResultMessage):
                u = msg.usage or {}
                tokens = {
                    "in": int(u.get("input_tokens", 0))
                    + int(u.get("cache_read_input_tokens", 0))
                    + int(u.get("cache_creation_input_tokens", 0)),
                    "out": int(u.get("output_tokens", 0)),
                }
                if msg.result and not text:
                    text = msg.result
    m = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S)
    changes = json.loads(m[-1]).get("changes", []) if m else []
    out = {
        "source": "post-hoc",
        "parent": parent,
        "model": model,
        "tokens": tokens,
        "changes": changes,
    }
    (AGENTS_DIR / name / "change_log.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n"
    )
    return out
