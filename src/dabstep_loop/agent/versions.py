"""Agent versions are folders: `agents/vN/{system.md, agent.yaml, helper.py}`.

Two of those files are the optimiser's only surfaces (`system.md`, `helper.py`);
`agent.yaml` is frozen across a loop cycle so a comparison is between prompts
and helpers, not between budgets. The fingerprint is what a run is logged
against, so two runs of the same bytes compare and two runs of different bytes
never masquerade as one version.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from dabstep_loop.config import AGENTS_DIR

SURFACES = ("system.md", "helper.py")
FROZEN = ("agent.yaml",)


@dataclass(frozen=True)
class AgentConfig:
    model: str = "haiku"
    max_turns: int = 20
    tools: list[str] = field(default_factory=lambda: ["mcp__py__execute_python"])
    effort: str | None = None
    timeout_s: int = 270
    exec_timeout_s: int = 120


@dataclass(frozen=True)
class AgentVersion:
    name: str
    path: Path
    system_prompt: str
    config: AgentConfig
    helper: str | None
    fingerprint: str

    @property
    def helper_path(self) -> Path | None:
        p = self.path / "helper.py"
        return p if p.exists() else None

    def files(self) -> dict[str, str]:
        out = {
            "system.md": self.system_prompt,
            "agent.yaml": (self.path / "agent.yaml").read_text(),
        }
        if self.helper is not None:
            out["helper.py"] = self.helper
        return out


def _fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    for name in sorted(SURFACES + FROZEN):
        p = path / name
        if p.exists():
            h.update(name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def load_version(name: str) -> AgentVersion:
    path = AGENTS_DIR / name
    if not (path / "system.md").exists():
        raise FileNotFoundError(f"no agent at {path}")
    cfg_raw = (
        yaml.safe_load((path / "agent.yaml").read_text()) if (path / "agent.yaml").exists() else {}
    )
    config = AgentConfig(**(cfg_raw or {}))
    helper = (path / "helper.py").read_text() if (path / "helper.py").exists() else None
    return AgentVersion(
        name=name,
        path=path,
        system_prompt=(path / "system.md").read_text(),
        config=config,
        helper=helper,
        fingerprint=_fingerprint(path),
    )


def list_versions() -> list[AgentVersion]:
    names = sorted(
        (p.name for p in AGENTS_DIR.iterdir() if p.is_dir() and re.fullmatch(r"v\d+", p.name)),
        key=lambda n: int(n[1:]),
    )
    return [load_version(n) for n in names]


def next_version_name() -> str:
    versions = list_versions()
    return f"v{int(versions[-1].name[1:]) + 1}" if versions else "v0"


def helper_signatures(helper_source: str) -> str:
    """The `def` lines and first docstring line of a helper, for the prompt."""
    lines: list[str] = []
    src = helper_source.splitlines()
    for i, line in enumerate(src):
        if line.startswith("def "):
            sig = line.strip()
            doc = ""
            if i + 1 < len(src) and src[i + 1].strip().startswith(('"""', "'''")):
                doc = src[i + 1].strip().strip('"').strip("'").strip()
            lines.append(f"{sig}  # {doc}" if doc else sig)
    return "\n".join(lines)
