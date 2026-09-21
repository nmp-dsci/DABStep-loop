"""Paths and settings. One place; nothing else reads `os.environ` for these.

`Settings` boots keyless: the absence of a key is a legitimate state (demo mode,
CI, the scorer) and only a call that would actually reach a model asks for one.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
CONTEXT_DIR = DATA_DIR / "context"
SAMPLES_DIR = DATA_DIR / "samples"
TASKS_DIR = DATA_DIR / "tasks"
AGENTS_DIR = ROOT / "agents"
RUNS_DIR = ROOT / "runs"
LOOP_DIR = ROOT / "loop"
LEDGER_PATH = LOOP_DIR / "ledger.jsonl"
REGISTRY_PATH = LOOP_DIR / "registry.json"
WORKSPACE_DIR = ROOT / "workspace"
FRONTEND_DIST = ROOT / "frontend" / "dist"

HF_DATASET = "adyen/DABstep"
DEV_SPLIT = "dev"
ALL_SPLIT = "default"


class Settings(BaseModel):
    """Runtime settings, read once from the environment."""

    billing: str = "subscription"
    demo_mode: bool = False
    mlflow_tracking_uri: str = "http://localhost:5000"
    code_sha: str = "unknown"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            billing=os.environ.get("BILLING", "subscription").strip().lower(),
            demo_mode=os.environ.get("DEMO_MODE", "").strip() in {"1", "true", "yes"},
            mlflow_tracking_uri=os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000"),
            code_sha=os.environ.get("DABSTEP_CODE_SHA", "unknown"),
        )


def settings() -> Settings:
    return Settings.from_env()


def context_dir() -> Path:
    """The data the agent reads: the full download if present, else the committed sample.

    The demo image only carries `data/samples/`, so a read-only deployment and a
    CI run see the same files a developer sees, minus the 23 MB payments.csv.
    """
    if (CONTEXT_DIR / "payments.csv").exists():
        return CONTEXT_DIR
    return SAMPLES_DIR
