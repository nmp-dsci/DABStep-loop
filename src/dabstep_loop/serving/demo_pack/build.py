"""`make demo-pack`: record the champion's dev-10 as the replay pack the demo serves.

The public deployment has no model. `/api/ask` there replays a recorded
session — the same events a live run streams, at a readable pace — for the ten
questions the champion actually answered, and declines any other question.
What a visitor watches is a real trace, attributed to the run it came from.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dabstep_loop.config import RUNS_DIR
from dabstep_loop.tracking.registry import read_registry

PACK_PATH = Path(__file__).with_name("pack.json")


def trace_events(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """The stream a live `/api/ask` emits, derived from a saved trace."""
    events: list[dict[str, Any]] = []
    for m in trace.get("trace", []):
        if m["role"] == "assistant":
            for b in m["content"]:
                if b["type"] == "tool_use":
                    events.append(
                        {
                            "type": "tool_use",
                            "name": b["name"],
                            "code": str(b["input"].get("code", "")),
                        }
                    )
                elif b["type"] == "text" and b["text"].strip():
                    events.append({"type": "text", "text": b["text"]})
        elif m["role"] == "tool":
            for b in m["content"]:
                if b["type"] == "tool_result":
                    events.append(
                        {
                            "type": "tool_result",
                            "text": str(b.get("content", ""))[:4000],
                            "is_error": bool(b.get("is_error")),
                        }
                    )
    events.append(
        {
            "type": "final",
            "agent_answer": trace.get("agent_answer", ""),
            "n_turns": trace.get("n_turns"),
            "duration_ms": trace.get("duration_ms"),
            "input_tokens": trace.get("input_tokens"),
            "output_tokens": trace.get("output_tokens"),
            "model": trace.get("model"),
            "terminal_reason": trace.get("terminal_reason"),
            "error": trace.get("error"),
        }
    )
    return events


def build_pack(run_id: str | None = None, path: Path = PACK_PATH) -> Path:
    if run_id is None:
        champ = read_registry().get("champion") or {}
        run_id = str(champ.get("run_id") or "")
    if not run_id:
        raise SystemExit("no champion run to record; run `make smoke` and `make promote` first")
    run_dir = RUNS_DIR / run_id
    meta = json.loads((run_dir / "run.json").read_text())
    items: list[dict[str, Any]] = []
    for line in (run_dir / "results.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        trace_path = run_dir / "traces" / f"{r['task_id']}.json"
        trace = json.loads(trace_path.read_text()) if trace_path.exists() else {}
        items.append(
            {
                "task_id": r["task_id"],
                "level": r["level"],
                "question": r["question"],
                "gold": r["gold"],
                "agent_answer": r["agent_answer"],
                "correct": r["correct"],
                "events": trace_events(trace) if trace else [],
            }
        )
    pack = {
        "run_id": run_id,
        "agent": meta["agent"],
        "fingerprint": meta["fingerprint"],
        "model": meta["model"],
        "items": items,
    }
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=1) + "\n")
    return path


def read_pack(path: Path = PACK_PATH) -> dict[str, Any]:
    if path.exists():
        return dict(json.loads(path.read_text()))
    return {"run_id": None, "items": []}
