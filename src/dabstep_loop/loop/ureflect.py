"""Unsupervised reflection (S4): one read-only session over a probe run writes the family cards.

The reflector sees, per family, what a rule cannot: the probe traces side by
side, the method each used (S1), where two passes disagreed (S2), which
invariants failed and between which tasks (S3), which answers broke the format
(S5), the current card, and the dev-10 evidence for anchored families. It rules
on the canonical method with the manual open, names the helper entry point the
family needs (existing or missing), picks one few-shot from a probe that passed
every check, and sets the status: `verified` only when the invariants passed
and the method cites the manual; `provisional` when consistent but unproven;
`open` when the method is wrong, unstable or unexplained.

It writes nothing itself. The harness writes `loop/families/Fnn.json` from its
JSON reply and one ledger entry of kind `ureflect`. The next optimiser reads
the cards; that is how a reflection changes a version.
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
    HookMatcher,
    ResultMessage,
    TextBlock,
)

from dabstep_loop.agent.llm import EFFORT, require_live, resolve_model, subscription_env
from dabstep_loop.agent.versions import load_version
from dabstep_loop.config import ROOT, RUNS_DIR
from dabstep_loop.data.tasks import load_tasks
from dabstep_loop.eval.runner import load_run
from dabstep_loop.loop.families import FAMILIES, FAMILIES_DIR, coverage
from dabstep_loop.loop.ledger import append_entry, next_cycle_number, read_ledger
from dabstep_loop.loop.lenses import read_lenses
from dabstep_loop.loop.optimiser import condense_trace
from dabstep_loop.loop.signals import compute, read_signals
from dabstep_loop.tracking.registry import read_registry

MAX_TURNS = 60
TRACE_CHARS = 2600
STATUSES = ("verified", "provisional", "open")


def read_card(fid: str) -> dict[str, Any] | None:
    p = FAMILIES_DIR / f"{fid}.json"
    return dict(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None


def read_cards() -> dict[str, dict[str, Any]]:
    return {f.id: c for f in FAMILIES if (c := read_card(f.id)) is not None}


def _dev_evidence(agent: str) -> dict[str, list[dict[str, Any]]]:
    """For anchored families: the champion's dev-10 outcome per anchor task."""
    champ = read_registry().get("champion") or {}
    run_id = str(champ.get("run_id") or "")
    if not run_id or champ.get("agent") != agent:
        return {}
    try:
        _, results = load_run(run_id)
    except FileNotFoundError:
        return {}
    by_task = {r.task_id: r for r in results}
    out: dict[str, list[dict[str, Any]]] = {}
    for row in coverage():
        for tid in row["dev_anchor"]:
            r = by_task.get(tid)
            if r:
                out.setdefault(row["id"], []).append(
                    {
                        "task_id": tid,
                        "correct": r.correct,
                        "answer": r.agent_answer,
                        "turns": r.n_turns,
                    }
                )
    return out


def build_prompt(run_id: str) -> str:
    meta, results = load_run(run_id)
    signals = read_signals(run_id) or compute(run_id)
    version = load_version(meta.agent)
    cards = read_cards()
    lenses = read_lenses() or {}
    lens_tasks = lenses.get("tasks", {})
    dev = _dev_evidence(meta.agent)
    tasks = {t.task_id: t for t in load_tasks("all")}
    run_dir = RUNS_DIR / run_id
    cov = {r["id"]: r for r in coverage()}

    blocks: list[str] = []
    for f in FAMILIES:
        b = signals["families"].get(f.id)
        if not b:
            continue
        c = cov[f.id]
        traces = []
        for tid in b["task_ids"]:
            t = tasks[tid]
            p = run_dir / "traces" / (f"{tid}.json" if meta.passes == 1 else f"{tid}_p1.json")
            flag = lens_tasks.get(tid, {}).get("boundary") or []
            traces.append(
                f"### task {tid} · answer {b['answers'].get(tid)!r}"
                + (f" · boundary: {'; '.join(flag)}" if flag else "")
                + f"\nQUESTION: {t.question}\nGUIDELINES: {t.guidelines}\nTRACE (pass 1, condensed):\n"
                + (condense_trace(p, limit=TRACE_CHARS) if p.exists() else "(no trace)")
            )
        checks = (
            "\n".join(
                f"- {ch['status'].upper()} {ch['name']} on {ch['tasks']}: {ch['detail']}"
                for ch in b["s3_checks"]
            )
            or "- no invariant applies to this family; rely on S1, S2, S5 and the manual"
        )
        methods = "\n".join(
            f"- {m['n']}× {m['signature']} ← tasks {m['tasks']}" for m in b["s1_methods"]
        )
        current = json.dumps(cards[f.id], indent=1) if f.id in cards else "none yet"
        devblock = (
            "\n".join(
                f"- dev task {d['task_id']}: {'PASS' if d['correct'] else 'FAIL'} · answer {d['answer']!r} · {d['turns']} turns"
                for d in dev.get(f.id, [])
            )
            or "- no dev-10 anchor: this family has never been checked against gold"
        )
        blocks.append(
            f"""## {f.id} · {f.name} · {c["tasks"]} of the 450 · {c["templates"]} templates
OPERATION: {f.operation}
INVARIANT: {f.invariant}
DEV-10 ANCHORS:
{devblock}
SIGNALS on this probe ({b["n"]} tasks): S1 modal share {b["s1_modal_share"]} · S2 self-agreement {b["s2_agreement"]} · S3 {b["s3_passed"]} passed / {b["s3_failed"]} failed / {b["s3_skipped"]} skipped · S5 format {b["s5_compliance"]} (bad: {b["s5_bad"]}) · turns {b["turns_mean"]} · errors {b["errors"]}
S1 METHODS:
{methods}
S2 DISAGREED BETWEEN PASSES: {b["s2_disagree"]}
S3 CHECKS:
{checks}
CURRENT CARD:
{current}
PROBE TRACES:
{chr(10).join(traces)}
"""
        )

    history = [
        f"- {e.get('kind')} {e.get('cycle')}: {str(e.get('summary', e.get('outcome', '')))[:400]}"
        for e in read_ledger()[-8:]
    ]
    return f"""You are the unsupervised reflector in a DABstep benchmark loop. The agent under review is `agents/{meta.agent}/`
(Haiku 4.5, one stateful Python tool, a `helper` module it imports). It was run on a seeded sample of the 450
leaderboard tasks (run `{run_id}`, {meta.passes} passes per task). Those tasks have NO answers, and you must not
try to obtain any: you judge methods, not answers. The 450 fall into 12 operation families; ten dev tasks with gold
anchor five of them. Your job is one card per family that tells the next optimiser what to put in `system.md`
and `helper.py` so that every family is answered by one canonical, manual-backed method.

You may read the repo (`agents/{meta.agent}/`, `data/context/manual.md`, the data) and run read-only Python via
Bash to check a hypothesis about a method (never to compute a task's answer for its own sake). Do not write or
edit any file; the harness writes the cards from your reply.

# Ledger, most recent entries
{chr(10).join(history) or "- none"}

# The agent's system prompt
{version.system_prompt}

# The agent's helper (signatures)
{chr(10).join(line for line in (version.helper or "").splitlines() if line.startswith("def "))}

# The families
{chr(10).join(blocks)}

# What to decide, per family
1. The canonical method: which helper entry point (existing, or one to add — give its signature) and the steps,
   with the manual.md sections it follows. Where S1 shows conflicting methods, rule which is right and why.
2. The status: `verified` only if every applicable invariant passed, the passes agreed, and the method cites the
   manual; `provisional` if consistent but unproven (no invariant applies, or a dev anchor fails); `open` if the
   method is wrong, unstable, or you could not decide. An anchored family whose dev task fails is `open`.
3. Pitfalls: concrete, one line each, drawn from these traces (a wrong field, a wildcard missed, a turn budget
   burnt on hand loops, a format slip).
4. One few-shot: the task id of a probe whose trace used the canonical method and passed every check, and the
   one-line helper call that answered it. If none qualifies, null.
5. The prompt rule: one routing line for system.md — "if the question asks X → call Y; answer format Z".

Finish with exactly one fenced ```json block, nothing after it:
{{
  "summary": "three sentences: what the agent does well across families, where it is inconsistent, what to fix first",
  "cards": {{
    "F01": {{
      "status": "verified|provisional|open",
      "canonical_method": {{"helper": "name(args)", "exists": true|false, "steps": ["…"], "manual": ["§…"]}},
      "conflict_ruling": "when S1 showed two methods: which is right and the evidence; else empty",
      "pitfalls": ["…"],
      "few_shot": {{"task_id": "…", "question": "…", "code": "helper.…(…)"}} | null,
      "prompt_rule": "if the question … → … ; format …",
      "evidence": ["runs/{run_id}/traces/<task>.json", "manual.md §…"],
      "note": "anything the optimiser must know that fits nowhere above"
    }},
    "F02": {{ … }}, … all 12 families …
  }},
  "priorities": ["family ids in the order the optimiser should work them, worst first"]
}}
"""


def _write_cards(reply: dict[str, Any], run_id: str, cycle: int, model: str) -> list[str]:
    signals = read_signals(run_id) or {}
    cov = {r["id"]: r for r in coverage()}
    written: list[str] = []
    FAMILIES_DIR.mkdir(parents=True, exist_ok=True)
    for f in FAMILIES:
        got = (reply.get("cards") or {}).get(f.id)
        if not isinstance(got, dict):
            continue
        status = str(got.get("status", "open"))
        if status not in STATUSES:
            status = "open"
        old = read_card(f.id) or {}
        card = {
            "id": f.id,
            "name": f.name,
            "pattern": f.pattern,
            "operation": f.operation,
            "invariant": f.invariant,
            "members": cov[f.id]["tasks"],
            "templates": cov[f.id]["templates"],
            "dev_anchor": cov[f.id]["dev_anchor"],
            "status": status,
            "canonical_method": got.get("canonical_method") or {},
            "conflict_ruling": got.get("conflict_ruling") or "",
            "pitfalls": list(got.get("pitfalls") or []),
            "few_shot": got.get("few_shot"),
            "prompt_rule": got.get("prompt_rule") or "",
            "note": got.get("note") or "",
            "evidence": list(got.get("evidence") or []),
            "signals": {
                k: v
                for k, v in (signals.get("families", {}).get(f.id) or {}).items()
                if k
                in {
                    "n",
                    "s1_modal_share",
                    "s2_agreement",
                    "s3_passed",
                    "s3_failed",
                    "s3_skipped",
                    "s5_compliance",
                    "turns_mean",
                }
            },
            "probe_run": run_id,
            "model": model,
            "history": [
                *old.get("history", []),
                {"cycle": cycle, "kind": "ureflect", "run": run_id, "status": status},
            ],
        }
        (FAMILIES_DIR / f"{f.id}.json").write_text(
            json.dumps(card, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written.append(f.id)
    return written


async def run_ureflection(run_id: str, model: str = "sonnet") -> dict[str, Any]:
    require_live()
    meta, _ = load_run(run_id)
    if meta.kind != "probe":
        raise SystemExit(f"{run_id} is not a probe run (kind={meta.kind}); ureflect reads probes")

    async def deny_writes(input_data: Any, tool_use_id: str | None, context: Any) -> Any:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Reflection is read-only; the harness writes the cards.",
            }
        }

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
    error: str | None = None
    if m:
        try:
            parsed = json.loads(m[-1])
        except json.JSONDecodeError as e:
            error = f"json: {e}"
    else:
        error = "no json block in the reply"
    cycle = next_cycle_number()
    written = _write_cards(parsed, run_id, cycle, model) if parsed else []
    statuses = {fid: (read_card(fid) or {}).get("status") for fid in written}
    entry: dict[str, Any] = {
        "cycle": cycle,
        "kind": "ureflect",
        "champion": meta.agent,
        "agent": meta.agent,
        "probe_run": run_id,
        "challenger": None,
        "model": model,
        "summary": parsed.get("summary", text[:1500] if error else ""),
        "priorities": parsed.get("priorities", []),
        "cards_written": written,
        "statuses": statuses,
        "signals": (read_signals(run_id) or {}).get("composite"),
        "optimiser": {
            "turns": turns,
            "duration_ms": int((time.time() - started) * 1000),
            "cost_usd_est": None,
            "error": error,
        },
        "tokens": tokens,
        "outcome": {
            "verdict": "recorded" if written else "failed",
            "reason": error or f"{len(written)} cards",
        },
    }
    append_entry(entry)
    try:
        from dabstep_loop.tracking.mlflow_log import log_cycle

        log_cycle(entry)
    except Exception:  # noqa: BLE001
        pass
    return entry
