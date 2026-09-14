"""Log a run folder to the self-hosted MLflow (sqlite, :5600).

MLflow is the index, never the record: every artifact it holds is a copy of a
file in `runs/<id>/`. If the server is down the eval still completes and the
run folder is complete; `make snapshot` exports the experiment for the demo.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import mlflow

from dabstep_loop.config import settings

if TYPE_CHECKING:
    from dabstep_loop.eval.runner import RunMeta
    from dabstep_loop.eval.score import TaskResult

EXPERIMENT = "dabstep-loop"


def _client_setup() -> None:
    mlflow.set_tracking_uri(settings().mlflow_tracking_uri)
    mlflow.set_experiment(EXPERIMENT)


def log_run(run_dir: Path, meta: RunMeta, results: list[TaskResult]) -> str:
    """One MLflow run per eval run; returns the MLflow run id."""
    _client_setup()
    s = meta.summary or {}
    with mlflow.start_run(run_name=meta.run_id) as run:
        mlflow.set_tags(
            {
                "agent": meta.agent,
                "fingerprint": meta.fingerprint,
                "model": meta.model,
                "split": meta.split,
                "code_sha": meta.code_sha,
                "kind": "eval",
            }
        )
        mlflow.log_params(
            {
                "agent": meta.agent,
                "model": meta.model,
                "split": meta.split,
                "workers": meta.workers,
                "passes": meta.passes,
                "n_tasks": meta.n_tasks,
                "fingerprint": meta.fingerprint,
            }
        )
        if s.get("n_scored"):
            mlflow.log_metrics(
                {
                    "passed": float(s["passed"]),
                    "pass_rate": float(s["pass_rate"] or 0.0),
                    "easy_passed": float(s["easy_passed"]),
                    "hard_passed": float(s["hard_passed"]),
                }
            )
        mlflow.log_metrics(
            {
                "cost_usd": float(s.get("cost_usd", 0.0)),
                "duration_s": float(s.get("duration_ms", 0)) / 1000,
                "errors": float(len(s.get("errored_ids", []))),
                "turns_total": float(sum(r.n_turns for r in results)),
                "input_tokens": float(sum(r.input_tokens for r in results)),
                "output_tokens": float(sum(r.output_tokens for r in results)),
            }
        )
        for r in results:
            if r.correct is not None:
                mlflow.log_metric(f"task_{r.task_id}", 1.0 if r.correct else 0.0)
        for name in ("run.json", "results.jsonl", "submission.jsonl"):
            if (run_dir / name).exists():
                mlflow.log_artifact(str(run_dir / name))
        if (run_dir / "agent").is_dir():
            mlflow.log_artifacts(str(run_dir / "agent"), artifact_path="agent")
        if (run_dir / "traces").is_dir():
            mlflow.log_artifacts(str(run_dir / "traces"), artifact_path="traces")
        return str(run.info.run_id)


def log_cycle(entry: dict[str, object]) -> str | None:
    """A loop cycle as its own MLflow run, tagged `kind=cycle`, so the UI shows the story."""
    try:
        _client_setup()
        with mlflow.start_run(run_name=f"cycle-{entry.get('cycle')}") as run:
            mlflow.set_tags(
                {
                    "kind": str(entry.get("kind", "cycle")),
                    "champion": str(entry.get("champion")),
                    "challenger": str(entry.get("challenger")),
                }
            )
            outcome = entry.get("outcome") or {}
            if isinstance(outcome, dict):
                mlflow.set_tag("verdict", str(outcome.get("verdict")))
            tokens = entry.get("tokens") or {}
            if isinstance(tokens, dict):
                mlflow.log_metrics(
                    {
                        f"tokens_{k}": float(v)
                        for k, v in tokens.items()
                        if isinstance(v, int | float)
                    }
                )
            mlflow.log_dict(dict(entry), "ledger_entry.json")
            return str(run.info.run_id)
    except Exception:  # noqa: BLE001
        return None
