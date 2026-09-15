"""The per-task prompt: file structures, helper signatures, the question, the guidelines.

The system prompt (`agents/vN/system.md`) carries the behaviour; this carries
the facts of the task. Keeping them apart is what lets the optimiser edit one
file and the harness keep the other stable.
"""

from __future__ import annotations

from pathlib import Path

from dabstep_loop.agent.versions import AgentVersion, helper_signatures
from dabstep_loop.data.file_structures import render
from dabstep_loop.data.tasks import Task


def build_task_prompt(
    version: AgentVersion, task: Task, data_dir: Path, harness_rule: str = ""
) -> str:
    parts = [
        f"Available data files in '{data_dir}/':",
        render(),
        "",
        "Use the execute_python tool to load, explore and analyse the data. Variables persist between "
        "calls; pandas is preloaded as `pd`. Read manual.md and payments-readme.md first where the "
        "question depends on domain terms (fees, fraud, ACI, capture delay).",
    ]
    if version.helper:
        parts += [
            "",
            "A helper module is importable as `helper` (`from helper import *`). Prefer it over "
            "re-deriving the rules; its functions:",
            helper_signatures(version.helper),
        ]
    if harness_rule:
        parts += ["", harness_rule]
    parts += [
        "",
        f"QUESTION: {task.question}",
        "",
        f"GUIDELINES: {task.guidelines or 'N/A'}",
    ]
    return "\n".join(parts)
