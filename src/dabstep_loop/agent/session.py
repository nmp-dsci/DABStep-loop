"""One task, one Agent SDK session, one trace.

The session is the NVIDIA inference shape on the Agent SDK: a system prompt
from `agents/vN/system.md`, a single tool (`execute_python`), a turn budget, a
wall-clock budget, and a final `{"agent_answer": ...}`. Everything the model
saw and did is kept as the trace — the loop's optimiser reads these, so the
trace is the product as much as the answer is.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from dabstep_loop.agent.answer import extract_agent_answer
from dabstep_loop.agent.llm import require_live, resolve_model, subscription_env
from dabstep_loop.agent.prompt import build_task_prompt
from dabstep_loop.agent.tools.python_executor import ExecutorState, make_executor_server
from dabstep_loop.agent.versions import AgentVersion
from dabstep_loop.config import ROOT, WORKSPACE_DIR, context_dir
from dabstep_loop.data.tasks import Task


@dataclass
class Solve:
    task_id: str
    agent_answer: str
    final_text: str
    trace: list[dict[str, Any]] = field(default_factory=list)
    n_turns: int = 0
    duration_ms: int = 0
    cost_usd: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    terminal_reason: str | None = None
    session_id: str | None = None
    model: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _block_to_dict(b: Any) -> dict[str, Any]:
    if isinstance(b, TextBlock):
        return {"type": "text", "text": b.text}
    if isinstance(b, ThinkingBlock):
        return {"type": "thinking", "thinking": b.thinking}
    if isinstance(b, ToolUseBlock):
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    if isinstance(b, ToolResultBlock):
        content = b.content
        if isinstance(content, list):
            content = "\n".join(str(c.get("text", "")) for c in content if isinstance(c, dict))
        return {
            "type": "tool_result",
            "tool_use_id": b.tool_use_id,
            "content": content,
            "is_error": b.is_error,
        }
    return {"type": type(b).__name__, "repr": repr(b)[:2000]}


async def solve_task(
    version: AgentVersion,
    task: Task,
    model: str | None = None,
    effort: str | None = None,
    timeout_s: int | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> Solve:
    """Run one task through the agent and return the answer plus the full trace.

    `on_event` receives each tool call, tool result and text as it happens, in
    the same shape the demo pack replays — the live `/api/ask` streams these.
    """
    require_live()
    cfg = version.config
    model_id = resolve_model(model or cfg.model)
    timeout_s = timeout_s or cfg.timeout_s
    data_dir = context_dir()
    workdir = WORKSPACE_DIR / "tasks" / task.task_id
    workdir.mkdir(parents=True, exist_ok=True)

    state = ExecutorState(helper_path=version.helper_path)
    server = make_executor_server(state, cwd=ROOT, timeout_s=cfg.exec_timeout_s)

    options = ClaudeAgentOptions(
        system_prompt=version.system_prompt,
        model=model_id,
        tools=[],  # no built-in tools: the executor is the whole toolbox
        allowed_tools=list(cfg.tools),
        mcp_servers={"py": server},
        permission_mode="bypassPermissions",
        max_turns=cfg.max_turns,
        cwd=str(ROOT),
        env=subscription_env(),
        setting_sources=[],
        effort=effort or cfg.effort,  # type: ignore[arg-type]
    )
    prompt = build_task_prompt(version, task, data_dir)
    solve = Solve(task_id=task.task_id, agent_answer="", final_text="", model=model_id)
    solve.trace.append({"role": "system", "content": version.system_prompt})
    solve.trace.append({"role": "user", "content": prompt})
    started = time.time()
    final_text = ""

    async def _run() -> None:
        nonlocal final_text
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    blocks = [_block_to_dict(b) for b in msg.content]
                    solve.trace.append({"role": "assistant", "content": blocks})
                    texts = [b["text"] for b in blocks if b["type"] == "text"]
                    if texts:
                        final_text = texts[-1]
                    if on_event:
                        for b in blocks:
                            if b["type"] == "tool_use":
                                on_event(
                                    {
                                        "type": "tool_use",
                                        "name": b["name"],
                                        "code": str(b["input"].get("code", "")),
                                    }
                                )
                            elif b["type"] == "text" and b["text"].strip():
                                on_event({"type": "text", "text": b["text"]})
                elif isinstance(msg, UserMessage) and not isinstance(msg.content, str):
                    blocks = [_block_to_dict(b) for b in msg.content]
                    solve.trace.append({"role": "tool", "content": blocks})
                    if on_event:
                        for b in blocks:
                            if b["type"] == "tool_result":
                                on_event(
                                    {
                                        "type": "tool_result",
                                        "text": str(b.get("content", ""))[:4000],
                                        "is_error": bool(b.get("is_error")),
                                    }
                                )
                elif isinstance(msg, ResultMessage):
                    solve.n_turns = msg.num_turns
                    solve.cost_usd = msg.total_cost_usd
                    solve.session_id = msg.session_id
                    solve.terminal_reason = msg.terminal_reason or msg.subtype
                    usage = msg.usage or {}
                    solve.input_tokens = (
                        int(usage.get("input_tokens", 0))
                        + int(usage.get("cache_read_input_tokens", 0))
                        + int(usage.get("cache_creation_input_tokens", 0))
                    )
                    solve.output_tokens = int(usage.get("output_tokens", 0))
                    if msg.result and not final_text:
                        final_text = msg.result
                    if msg.is_error:
                        solve.error = f"{msg.subtype}: {(msg.errors or [msg.result or ''])[0]}"[
                            :500
                        ]

    try:
        await asyncio.wait_for(_run(), timeout=timeout_s)
    except TimeoutError:
        solve.error = f"timeout after {timeout_s}s"
        solve.terminal_reason = "timeout"
    except Exception as e:  # noqa: BLE001 - recorded on the result, the run continues
        solve.error = f"{type(e).__name__}: {e}"[:500]
    solve.duration_ms = int((time.time() - started) * 1000)
    solve.final_text = final_text
    solve.agent_answer = extract_agent_answer(final_text)
    solve.trace.append({"role": "executor", "content": state.history})
    return solve


def save_trace(path: Path, solve: Solve) -> None:
    import json

    path.write_text(json.dumps(solve.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
