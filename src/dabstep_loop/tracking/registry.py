"""The version registry: which agent folder is champion, which is challenger.

A JSON file committed with the repo (`loop/registry.json`), mirrored into the
MLflow model registry as aliases when the server is up. The file is the truth
because the demo image has no MLflow and the gate runs in CI with no server.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from dabstep_loop.config import LOOP_DIR, REGISTRY_PATH, settings

MODEL_NAME = "dabstep-agent"


def read_registry() -> dict[str, Any]:
    if REGISTRY_PATH.exists():
        return dict(json.loads(REGISTRY_PATH.read_text()))
    return {"champion": None, "challenger": None, "history": []}


def _write(reg: dict[str, Any]) -> None:
    LOOP_DIR.mkdir(exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2) + "\n")


def _entry(run_id: str) -> dict[str, Any]:
    from dabstep_loop.eval.runner import load_run

    meta, _ = load_run(run_id)
    s = meta.summary or {}
    return {
        "agent": meta.agent,
        "fingerprint": meta.fingerprint,
        "run_id": run_id,
        "model": meta.model,
        "split": meta.split,
        "passed": s.get("passed"),
        "n_scored": s.get("n_scored"),
        "at": datetime.now(UTC).isoformat(),
    }


def register(run_id: str, alias: str = "challenger") -> dict[str, Any]:
    reg = read_registry()
    e = _entry(run_id)
    reg[alias] = e
    reg.setdefault("history", []).append({"event": f"register:{alias}", **e})
    _write(reg)
    _mirror_alias(alias, e)
    return e


def promote(run_id: str) -> dict[str, Any]:
    reg = read_registry()
    e = _entry(run_id)
    reg["champion"] = e
    if reg.get("challenger") and reg["challenger"].get("agent") == e["agent"]:
        reg["challenger"] = None
    reg.setdefault("history", []).append({"event": "promote", **e})
    _write(reg)
    _mirror_alias("champion", e)
    return e


def champion_name() -> str | None:
    c = read_registry().get("champion")
    return str(c["agent"]) if c else None


def _mirror_alias(alias: str, e: dict[str, Any]) -> None:
    """Best effort: the same alias on the MLflow model registry."""
    try:
        import mlflow
        from mlflow import MlflowClient

        mlflow.set_tracking_uri(settings().mlflow_tracking_uri)
        client = MlflowClient()
        try:
            client.get_registered_model(MODEL_NAME)
        except Exception:  # noqa: BLE001
            client.create_registered_model(
                MODEL_NAME, description="DABstep agent versions (agents/vN)"
            )
        from dabstep_loop.eval.runner import load_run

        meta, _ = load_run(str(e["run_id"]))
        source = f"runs:/{meta.mlflow_run_id}/agent" if meta.mlflow_run_id else str(e["run_id"])
        mv = client.create_model_version(
            MODEL_NAME,
            source=source,
            run_id=meta.mlflow_run_id,
            tags={"agent": str(e["agent"]), "fingerprint": str(e["fingerprint"])},
        )
        client.set_registered_model_alias(MODEL_NAME, alias, mv.version)
    except Exception:  # noqa: BLE001 - the file is the record; the mirror is convenience
        return
