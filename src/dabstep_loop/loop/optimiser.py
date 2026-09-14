"""The optimiser: one Agent SDK session that reads every failure and writes the next version.

It sees the champion's two surfaces, every failed task's question, gold, answer
and full tool trace, and the ledger's history of what was tried before. It may
write only `agents/v(n+1)/system.md` and `helper.py` (a PreToolUse hook refuses
any other path; a checksum of the tree is compared after the session as well),
must verify a helper change against the dev gold in-session, and must finish by
writing `diagnosis.json` — the structured record the ledger stores.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from dabstep_loop.agent.llm import EFFORT, Effort, require_live, resolve_model, subscription_env
from dabstep_loop.agent.versions import SURFACES, AgentVersion, load_version, next_version_name
from dabstep_loop.config import AGENTS_DIR, ROOT, RUNS_DIR, context_dir
from dabstep_loop.eval.score import TaskResult
from dabstep_loop.loop.ledger import render_history

MAX_TURNS = 120
TRACE_CHARS = 9000

FAMILY_RULES = """4b. The family cards are the point of this cycle. For every family whose card says its helper entry point does
   not exist, add it to helper.py with that signature, a docstring that names the manual sections, and the
   additive fee model the champion already uses. For every family, add ONE routing row to a
   "## Question families (route first, then compute)" table in system.md: `if the question asks … → call
   helper.… → answer format …`, and at most one example line per family (the card's few-shot, if any). Keep the
   prompt short: one row and at most one example per family, no prose.
4c. Verify a new entry point in-session against an invariant, not against gold: e.g. run it for a merchant's
   day, its month and its year and check ids(day) ⊆ ids(month) ⊆ ids(year) or fees(day) ≤ fees(month) ≤
   fees(year); run a min and a max steer-traffic for the same merchant and check the schemes differ. Record
   what you ran in the diagnosis. Never compute or record an answer for a leaderboard task as an answer.
4d. Work the families in the reflector's priority order; an `open` family with a failed invariant is worth
   more than polishing a `verified` one."""


@dataclass
class OptimiserOutput:
    new_version: str
    diagnosis: dict[str, Any]
    n_turns: int = 0
    duration_ms: int = 0
    cost_usd: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    transcript: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def condense_trace(trace_path: Path, limit: int = TRACE_CHARS) -> str:
    """The tool calls and their outputs, in order; the parts the diagnosis needs."""
    if not trace_path.exists():
        return "(no trace)"
    d = json.loads(trace_path.read_text())
    lines: list[str] = []
    for m in d.get("trace", []):
        if m["role"] == "assistant":
            for b in m["content"]:
                if b["type"] == "tool_use":
                    lines.append("### execute_python\n" + str(b["input"].get("code", "")).strip())
                elif b["type"] == "text" and b["text"].strip():
                    lines.append("### assistant\n" + b["text"].strip())
        elif m["role"] == "tool":
            for b in m["content"]:
                if b["type"] == "tool_result":
                    lines.append("### output\n" + str(b.get("content", "")).strip()[:1500])
    text = "\n".join(lines)
    if len(text) > limit:
        text = text[: limit // 2] + "\n…[middle of trace elided]…\n" + text[-limit // 2 :]
    meta = {k: d.get(k) for k in ("n_turns", "duration_ms", "terminal_reason", "error")}
    return f"{json.dumps(meta)}\n{text}"


def render_families_block(probe_run_id: str, trace_chars: int = 3000) -> str:
    """The family cards and the probe's failed invariants, for an unsupervised cycle's optimiser.

    Cards come first, worst status first, each with its canonical method, the
    prompt rule and the few-shot the reflector chose. Then every invariant the
    probe failed, with both tasks' questions, answers and condensed traces, so the
    contradiction can be read without gold."""
    from dabstep_loop.loop.families import FAMILIES
    from dabstep_loop.loop.signals import read_signals
    from dabstep_loop.loop.ureflect import read_cards

    cards = read_cards()
    if not cards:
        return "No family cards yet (run `dabstep ureflect` on a probe first)."
    order = {"open": 0, "provisional": 1, "verified": 2}
    lines: list[str] = []
    for f in sorted(
        FAMILIES, key=lambda f: order.get(cards.get(f.id, {}).get("status", "open"), 0)
    ):
        c = cards.get(f.id)
        if not c:
            continue
        m = c.get("canonical_method") or {}
        fs = c.get("few_shot") or {}
        lines.append(
            f"## {f.id} · {f.name} · {c.get('members')} of the 450 · status {c.get('status')}\n"
            f"OPERATION: {f.operation}\nINVARIANT: {f.invariant}\n"
            f"CANONICAL METHOD: {m.get('helper')} (exists in helper.py: {m.get('exists')})\n"
            + "".join(f"  - {st}\n" for st in m.get("steps", []))
            + f"  manual: {m.get('manual')}\n"
            f"PROMPT RULE: {c.get('prompt_rule')}\n"
            + (f"CONFLICT RULING: {c.get('conflict_ruling')}\n" if c.get("conflict_ruling") else "")
            + "".join(f"PITFALL: {pf}\n" for pf in c.get("pitfalls", []))
            + (
                f"FEW-SHOT: task {fs.get('task_id')}: {fs.get('question')} → {fs.get('code')}\n"
                if fs
                else "FEW-SHOT: none qualified\n"
            )
            + (f"NOTE: {c.get('note')}\n" if c.get("note") else "")
            + f"SIGNALS on the probe: {c.get('signals')}\n"
        )
    sig = read_signals(probe_run_id) or {}
    from dabstep_loop.data.tasks import load_tasks

    tasks = {t.task_id: t for t in load_tasks("all")}
    run_dir = RUNS_DIR / probe_run_id
    passes = int(sig.get("passes", 1))
    failed: list[str] = []
    for fid, b in (sig.get("families") or {}).items():
        for ch in b.get("s3_checks", []):
            if ch.get("status") != "failed":
                continue
            parts = [f"### {fid} · FAILED invariant: {ch['name']} · {ch['detail']}"]
            for tid in ch["tasks"]:
                t = tasks.get(tid)
                p = run_dir / "traces" / (f"{tid}.json" if passes == 1 else f"{tid}_p1.json")
                parts.append(
                    f"task {tid}: {t.question if t else '?'}\nANSWER: {b.get('answers', {}).get(tid)!r}\nTRACE:\n"
                    + (condense_trace(p, limit=trace_chars) if p.exists() else "(no trace)")
                )
            failed.append("\n".join(parts))
        for tid in b.get("s2_disagree", []):
            failed.append(
                f"### {fid} · two passes DISAGREED on task {tid}: {tasks[tid].question if tid in tasks else tid}"
            )
    return (
        "# Family cards (from the unsupervised reflector; worst status first)\n"
        + "\n".join(lines)
        + "\n# Contradictions the probe proved without gold\n"
        + ("\n".join(failed) or "none: every applicable invariant passed and both passes agreed")
    )


def build_prompt(
    champion: AgentVersion,
    new_name: str,
    run_id: str,
    failures: list[TaskResult],
    families_block: str = "",
) -> str:
    run_dir = RUNS_DIR / run_id
    blocks: list[str] = []
    for r in failures:
        blocks.append(
            f"## Task {r.task_id} ({r.level})\n"
            f"QUESTION: {r.question}\n"
            f"GOLD: {r.gold}\n"
            f"AGENT ANSWER: {r.agent_answer!r}\n"
            f"ERROR: {r.error or 'none'} · turns {r.n_turns}\n"
            f"TRACE:\n{condense_trace(run_dir / 'traces' / f'{r.task_id}.json')}\n"
        )
    gold_lines = "\n".join(f"- {r.task_id}: {r.gold}" for r in failures)
    held = held_challengers(champion.name)
    held_block = (
        "\n".join(
            f"- `agents/{h['challenger']}/` (cycle {h['cycle']}, held: {h['reason']}; passes {h['passes']}; fixed {h['fixed']}; "
            f"broke {h['broken']}). Its system.md and helper.py are on disk: read them, and copy what held — "
            "a held challenger is a starting point, not a rejected one. Do not repeat what broke."
            for h in held
        )
        or "none"
    )
    return f"""You are the optimiser in a benchmark improvement loop for an agent that answers DABstep questions
(tabular QA over a payments dataset) with a Claude Haiku 4.5 model and one tool: a stateful Python executor.

The champion is `agents/{champion.name}/`. {"It passed some of the dev tasks and failed the ones below." if failures else "It passed every dev task; this cycle is driven by the family cards below, not by dev failures."}
A copy of the champion is already at `agents/{new_name}/`. Your job is to turn that copy into a better
version by editing **only two files**: `agents/{new_name}/system.md` (the agent's system prompt) and
`agents/{new_name}/helper.py` (a module the agent imports as `helper` inside the executor).
`agent.yaml` is frozen; do not touch it, and do not edit anything outside `agents/{new_name}/`
— the harness refuses the cycle if you do.

The data lives in `{context_dir()}/` (payments.csv, fees.json, merchant_data.json, manual.md, ...).
`manual.md` defines the fee rules; read the relevant sections before deciding a root cause.

# What was tried before
{render_history([r.task_id for r in failures])}

# Held challengers of this champion (their folders still exist)
{held_block}

# The champion's surfaces
## agents/{champion.name}/system.md
{champion.system_prompt}

## agents/{champion.name}/helper.py
```python
{champion.helper or "(no helper yet)"}
```

# The failures ({len(failures)} of the dev split)
{chr(10).join(blocks) or "none"}

{families_block}

# Method
1. For each failed task, find the root cause from the trace: the wrong rule, the missing null-as-wildcard
   semantics, an unread manual section, a format mistake, running out of turns, and so on. Classify each as a
   prompt problem or a helper problem. A task that failed for a reason already tried and not fixed needs a
   different fix, not the same one again.
2. Make the change in the two surfaces. Prefer helper functions with clear signatures and docstrings for
   anything computational (fee rule matching, monthly metrics, intracountry flags); prefer short, concrete
   prompt rules for behaviour (which file to read, answer format, when to stop). Keep the output-format
   contract: the agent must end with exactly `{{"agent_answer": ...}}`.
3. Verify helper changes in-session: run `uv run python -c "..."` or a small script from the repo root with
   `sys.path.insert(0, "agents/{new_name}")` and check your helper reproduces these gold answers:
{gold_lines}
   Do not claim a fix you did not run. If a gold cannot be reproduced, say so in the diagnosis.
4. Do not regress: keep everything that made the champion pass its tasks. Do not hard-code any task's answer
   or any task-specific branch; the 450 leaderboard tasks are permutations of these questions with other
   merchants, months and fees.
{FAMILY_RULES if families_block else ""}
5. Finish by writing `agents/{new_name}/diagnosis.json` with exactly this shape:
{{
  "diagnoses": [
    {{"task_id": "…", "symptom": "…", "root_cause": "…", "surface": "system.md|helper.py|both",
      "change": "one sentence", "verified_in_session": true|false, "verification": "what you ran and saw"}}
  ],
  "prompt_diff_summary": "what changed in system.md, one line",
  "helper_diff_summary": "what changed in helper.py, one line",
  "expected_to_fix": ["task ids"],
  "risks": ["what might regress and why you think it will not"],
  "changes": [
    {{"file": "system.md|helper.py", "anchor": "the function name, or the first five words of the edited block",
      "what": "what the edit does, one sentence", "why": "the evidence that made you do it — a trace, a manual section, a number",
      "task_ids": ["tasks this edit is for"]}}
  ]
}}
`changes` is the change log: one entry per distinct edit (an added function, a removed one, a rewritten rule), so
that a reader looking at the diff can find the reason next to the hunk. Every hunk in the diff should be covered.
Then stop. The harness evaluates `{new_name}` on the whole dev split, applies the gate (a one-sided McNemar test
on the paired tasks: fixes must outweigh breaks with p < 0.05 — one break costs three extra fixes), and records the outcome next to your diagnosis in the ledger.
"""


def held_challengers(champion_name: str) -> list[dict[str, Any]]:
    """Earlier challengers of this champion that the gate held: real progress the next version may reuse."""
    from dabstep_loop.loop.ledger import read_ledger

    out: list[dict[str, Any]] = []
    for e in read_ledger():
        o = e.get("outcome") or {}
        if (
            e.get("kind", "cycle") == "cycle"
            and e.get("champion") == champion_name
            and o.get("verdict") == "hold"
            and e.get("challenger")
        ) and (AGENTS_DIR / str(e["challenger"])).exists():
            out.append(
                {
                    "cycle": e.get("cycle"),
                    "challenger": e["challenger"],
                    "reason": o.get("reason"),
                    "passes": o.get("passes"),
                    "fixed": o.get("fixed"),
                    "broken": o.get("broken"),
                }
            )
    return out


def _copy_champion(champion: AgentVersion, new_name: str) -> Path:
    new_dir = AGENTS_DIR / new_name
    if new_dir.exists():
        shutil.rmtree(new_dir)
    new_dir.mkdir(parents=True)
    for name in ("system.md", "agent.yaml", "helper.py"):
        src = champion.path / name
        if src.exists():
            shutil.copyfile(src, new_dir / name)
    return new_dir


GUARDED = (
    "agents",
    "loop/families",
    "src/dabstep_loop/agent",
    "src/dabstep_loop/eval",
    "src/dabstep_loop/loop",
    "src/dabstep_loop/data",
    "tests",
    "data/tasks",
    "data/file_structures.json",
    "Makefile",
    "pyproject.toml",
)


def tree_checksum(exclude: Path) -> dict[str, int]:
    """mtime+size of every file the optimiser could cheat with, outside its own version folder.

    The guarded set is explicit: the agent code, the scorer, the loop, the
    tasks and every other version. A change to any of these during the session
    rejects the cycle. Files outside the set (the viewer, the frontend, docs)
    are not the optimiser's to edit either, but a change there cannot alter a
    score, so concurrent human work on them does not void a cycle.
    """
    out: dict[str, int] = {}
    for rel in GUARDED:
        base = ROOT / rel
        files = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
        for p in files:
            if exclude in p.parents or p == exclude or "__pycache__" in p.parts:
                continue
            st = p.stat()
            out[str(p.relative_to(ROOT))] = int(st.st_mtime_ns) ^ st.st_size
    return out


async def run_optimiser(
    champion: AgentVersion,
    run_id: str,
    failures: list[TaskResult],
    model: str = "sonnet",
    effort: Effort = EFFORT,
    families_block: str = "",
) -> OptimiserOutput:
    require_live()
    new_name = next_version_name()
    new_dir = _copy_champion(champion, new_name)
    allowed_prefix = str(new_dir.resolve())
    before = tree_checksum(new_dir)

    async def guard_writes(
        input_data: Any, tool_use_id: str | None, context: Any
    ) -> dict[str, Any]:
        """Refuse a Write/Edit outside agents/v(n+1)/ and any touch of agent.yaml."""
        path = str(input_data.get("tool_input", {}).get("file_path", ""))
        resolved = str(Path(path).resolve()) if path else ""
        ok = resolved.startswith(allowed_prefix) and not resolved.endswith("agent.yaml")
        if ok:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Only agents/{new_name}/system.md, helper.py and diagnosis.json may be written.",
            }
        }

    options = ClaudeAgentOptions(
        model=resolve_model(model),
        effort=effort,
        allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        permission_mode="bypassPermissions",
        max_turns=MAX_TURNS,
        cwd=str(ROOT),
        env=subscription_env(),
        setting_sources=[],
        hooks={"PreToolUse": [HookMatcher(matcher="Write|Edit|MultiEdit", hooks=[guard_writes])]},  # type: ignore[list-item]
    )
    prompt = build_prompt(champion, new_name, run_id, failures, families_block)
    out = OptimiserOutput(new_version=new_name, diagnosis={})
    out.transcript.append({"role": "user", "content": prompt})
    started = time.time()
    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for b in msg.content:
                        if isinstance(b, TextBlock) and b.text.strip():
                            out.transcript.append({"role": "assistant", "content": b.text})
                        elif isinstance(b, ToolUseBlock):
                            out.transcript.append(
                                {"role": "tool_use", "name": b.name, "input": b.input}
                            )
                elif isinstance(msg, ResultMessage):
                    out.n_turns = msg.num_turns
                    out.cost_usd = msg.total_cost_usd
                    u = msg.usage or {}
                    out.input_tokens = (
                        int(u.get("input_tokens", 0))
                        + int(u.get("cache_read_input_tokens", 0))
                        + int(u.get("cache_creation_input_tokens", 0))
                    )
                    out.output_tokens = int(u.get("output_tokens", 0))
                    if msg.is_error:
                        out.error = f"{msg.subtype}: {(msg.errors or [''])[0]}"[:500]
    except Exception as e:  # noqa: BLE001
        out.error = f"{type(e).__name__}: {e}"[:500]
    out.duration_ms = int((time.time() - started) * 1000)

    after = tree_checksum(new_dir)
    touched = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    if touched:
        out.error = (
            out.error + "; " if out.error else ""
        ) + f"optimiser changed files outside agents/{new_name}: {touched[:10]}"
    if (new_dir / "agent.yaml").read_bytes() != (champion.path / "agent.yaml").read_bytes():
        out.error = (out.error + "; " if out.error else "") + "agent.yaml was modified (frozen)"
    diag_path = new_dir / "diagnosis.json"
    if diag_path.exists():
        try:
            out.diagnosis = json.loads(diag_path.read_text())
        except json.JSONDecodeError as e:
            out.error = (out.error + "; " if out.error else "") + f"diagnosis.json unreadable: {e}"
    else:
        out.error = (out.error + "; " if out.error else "") + "no diagnosis.json written"
    new_version = load_version(new_name)
    if all(new_version.files().get(s) == champion.files().get(s) for s in SURFACES):
        out.error = (out.error + "; " if out.error else "") + "no change to either surface"
    (new_dir / "optimiser_transcript.json").write_text(
        json.dumps(out.transcript, ensure_ascii=False, indent=1)
    )
    return out
