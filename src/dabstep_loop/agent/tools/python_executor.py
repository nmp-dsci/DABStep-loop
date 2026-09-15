"""The agent's only tool: a stateful Python executor, in-process, as an SDK MCP server.

One namespace per task, reset between tasks; pandas preloaded; a timeout per
call; and NVIDIA's loop-breaker — the same code run three times returns an
instruction to answer, not a fourth result. A REPL-style auto-print of a bare
final expression saves the model a `print()` on every exploration step.

Under a pruning harness (`agent/harness.py`) a long output is not returned in
full: the model sees its head plus a reference (`out#3`) and a `show()` function
re-opens any window of it. NVIDIA's "an ID where the function was" — the full
text never rides along in every later turn, but nothing is lost to the model.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig

# Execution is serialised across concurrent tasks: stdout redirection is
# process-wide, and pandas on a 138k-row frame is not the bottleneck the model is.
_EXEC_LOCK = threading.Lock()


@dataclass
class ExecutorState:
    namespace: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    calls: int = 0
    helper_path: Path | None = None
    prune_cap: int | None = None  # None: today's 12k truncation only
    prune_head: int = 600
    outputs: dict[str, str] = field(default_factory=dict)  # out#k → full text, when pruned

    def reset(self) -> None:
        self.namespace.clear()
        self.history.clear()
        self.outputs.clear()
        self.calls = 0


def _is_print_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"
    )


def _exec_with_auto_print(code: str, namespace: dict[str, Any]) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        exec(code, namespace)  # noqa: S102 - re-raise the real SyntaxError
        return
    if not tree.body:
        return
    last = tree.body[-1]
    if isinstance(last, ast.Expr) and not _is_print_call(last.value):
        if len(tree.body) > 1:
            head = ast.Module(body=tree.body[:-1], type_ignores=[])
            ast.fix_missing_locations(head)
            exec(compile(head, "<code>", "exec"), namespace)  # noqa: S102
        expr = ast.Expression(body=last.value)
        ast.fix_missing_locations(expr)
        result = eval(compile(expr, "<code>", "eval"), namespace)  # noqa: S307
        if result is not None:
            print(result)
    else:
        exec(compile(tree, "<code>", "exec"), namespace)  # noqa: S102


def _init_namespace(state: ExecutorState) -> None:
    """pandas preloaded, and the version's helper importable as `helper`.

    The helper is loaded from its file each task rather than through the import
    cache, so a champion and a challenger evaluated in one process never share
    a `helper` module.
    """
    import importlib.util

    import pandas as pd

    state.namespace["pd"] = pd
    state.namespace["__name__"] = "__task__"
    if state.prune_cap:
        state.namespace["show"] = _make_show(state)
    if state.helper_path and state.helper_path.exists():
        spec = importlib.util.spec_from_file_location("helper", state.helper_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules["helper"] = mod
            spec.loader.exec_module(mod)
            state.namespace["helper"] = mod


def _make_show(state: ExecutorState):  # type: ignore[no-untyped-def]
    """`show(ref, start=0, n=cap, find=None)`: a window of a pruned output, never over the cap."""
    cap = int(state.prune_cap or 1500)

    def show(ref: str, start: int = 0, n: int | None = None, find: str | None = None) -> None:
        key = str(ref).strip().lstrip("[").rstrip("]").split(":")[0].strip()
        if key not in state.outputs:
            print(f"no output {ref!r}; known: {', '.join(sorted(state.outputs)) or 'none'}")
            return
        full = state.outputs[key]
        width = max(
            100, min(int(n or cap), cap) - 160
        )  # the window plus its footer stays under the cap
        if find is not None:
            at = full.find(str(find), max(0, int(start)))
            if at < 0:
                print(f"{key}: {find!r} not found after {start}")
                return
            start = max(0, at - 80)
        start = max(0, int(start))
        end = min(len(full), start + width)
        print(full[start:end])
        if end < len(full):
            print(f"[{key} · chars {start}–{end} of {len(full)} · show({key!r}, start={end})]")
        else:
            print(f"[{key} · chars {start}–{end} of {len(full)} · end]")

    return show


def prune(body: str, state: ExecutorState) -> str:
    """Head plus a reference, when the body is over the profile's cap; else the body."""
    cap = state.prune_cap
    if not cap or len(body) <= cap:
        return body
    key = f"out#{len(state.outputs) + 1}"
    state.outputs[key] = body
    head = body[: state.prune_head]
    lines = body.count("\n") + 1
    return (
        f"{head}\n…[{key}: {len(body)} chars, {lines} lines — pruned; "
        f"show({key!r}) or show({key!r}, find='…') to read more]"
    )


def run_code(code: str, state: ExecutorState, timeout_s: int, cwd: Path) -> str:
    """Execute `code` in the task namespace; return captured output or the error."""
    if "\\n" in code and "\n" not in code:
        code = code.replace("\\n", "\n").replace("\\t", "\t")
    repeats = sum(1 for h in state.history if h["code"] == code)
    if repeats >= 2:
        return (
            f"STOP: you already ran this exact code {repeats} times with the same result. "
            'Do not call any more tools. Return your final answer now as {"agent_answer": "..."}.'
        )
    if "pd" not in state.namespace:
        _init_namespace(state)
    out, err = io.StringIO(), io.StringIO()
    start = time.time()
    result: dict[str, str] = {}

    def _run() -> None:
        with _EXEC_LOCK, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            old_cwd = Path.cwd()
            try:
                import os

                os.chdir(cwd)
                _exec_with_auto_print(code, state.namespace)
            except Exception as e:  # noqa: BLE001 - the model needs the error text
                result["error"] = f"Error ({type(e).__name__}): {e}"
            finally:
                os.chdir(old_cwd)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout_s)
    elapsed = time.time() - start
    if t.is_alive():
        text = f"Error (TimeoutError): execution exceeded {timeout_s}s. Simplify the code."
    elif "error" in result:
        text = result["error"]
        stdout = out.getvalue()
        if stdout:
            text = stdout + "\n" + text
    else:
        parts = []
        if out.getvalue():
            parts.append(out.getvalue())
        if err.getvalue():
            parts.append(f"[stderr] {err.getvalue()}")
        text = "\n".join(parts).rstrip()
        if len(text) > 12000:
            text = text[:6000] + "\n…[truncated]…\n" + text[-4000:]
        full = text
        text = prune(text, state)
        text = (text + "\n" if text else "") + f"[executed in {elapsed:.2f}s]"
        state.calls += 1
        entry: dict[str, Any] = {"code": code, "output": text, "elapsed_s": round(elapsed, 3)}
        if text != full + f"\n[executed in {elapsed:.2f}s]":
            entry["full_output"] = full
        state.history.append(entry)
        return text
    if len(text) > 12000:
        text = text[:6000] + "\n…[truncated]…\n" + text[-4000:]
    state.calls += 1
    state.history.append({"code": code, "output": text, "elapsed_s": round(elapsed, 3)})
    return text


def make_executor_server(
    state: ExecutorState, cwd: Path, timeout_s: int = 120
) -> McpSdkServerConfig:
    """An MCP server named `py` exposing `execute_python`, bound to one task's state."""

    @tool(
        "execute_python",
        "Execute Python code. Variables persist between calls; pandas is preloaded as `pd`. "
        "The last bare expression is printed like a notebook cell.",
        {"code": str},
    )
    async def execute_python(args: dict[str, Any]) -> dict[str, Any]:
        code = str(args.get("code", ""))
        text = await asyncio.to_thread(run_code, code, state, timeout_s, cwd)
        return {"content": [{"type": "text", "text": text}]}

    return create_sdk_mcp_server(name="py", version="1.0.0", tools=[execute_python])
