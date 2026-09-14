"""The API behind the frontend, and the frontend itself when a build is present.

Every read route serves a committed file: `runs/`, `agents/`, `loop/`, `data/`.
The one write-shaped route, `POST /api/ask`, streams a live agent session in
dev and replays the recorded pack in the demo image — where `llm.require_live`
raises before any model could be reached, so the public URL cannot bill.
"""

from __future__ import annotations

import asyncio
import csv
import json
import re
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from dabstep_loop import __version__
from dabstep_loop.agent.versions import list_versions, load_version
from dabstep_loop.config import FRONTEND_DIST, RUNS_DIR, SAMPLES_DIR, context_dir, settings
from dabstep_loop.data.file_structures import OUTPUT as FILE_STRUCTURES
from dabstep_loop.data.tasks import Task, load_tasks
from dabstep_loop.eval.compare import compare
from dabstep_loop.eval.runner import list_runs, load_run
from dabstep_loop.loop.ledger import read_ledger
from dabstep_loop.serving.demo_pack.build import read_pack, trace_events
from dabstep_loop.tracking.registry import read_registry
from dabstep_loop.tracking.snapshot import read_snapshot


def create_app() -> FastAPI:
    app = FastAPI(title="dabstep-loop", version=__version__)
    s = settings()

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        reg = read_registry()
        champ = reg.get("champion") or {}
        return {
            "status": "ok",
            "mode": "demo" if s.demo_mode else "live",
            "champion": champ.get("agent"),
            "champion_fingerprint": champ.get("fingerprint"),
            "code_sha": s.code_sha,
            "version": __version__,
        }

    # ── benchmark data ────────────────────────────────────────────────────
    @app.get("/api/tasks")
    def tasks(split: str = "dev") -> list[dict[str, Any]]:
        return [_task(t) for t in load_tasks(split)]

    @app.get("/api/tasks/{task_id}")
    def task(task_id: str) -> dict[str, Any]:
        for split in ("dev", "all"):
            for t in load_tasks(split):
                if t.task_id == task_id:
                    return {**_task(t), "split": split}
        raise HTTPException(404, "no such task")

    @app.get("/api/data/files")
    def data_files() -> dict[str, Any]:
        structures = json.loads(FILE_STRUCTURES.read_text()) if FILE_STRUCTURES.exists() else {}
        files = []
        for p in sorted(context_dir().iterdir()):
            if not p.is_file():
                continue
            files.append(
                {"name": p.name, "bytes": p.stat().st_size, "structure": structures.get(p.name, {})}
            )
        return {
            "dir": str(context_dir().relative_to(context_dir().parents[1])),
            "sampled": context_dir() == SAMPLES_DIR,
            "files": files,
        }

    @app.get("/api/data/files/{name}")
    def data_file(name: str, rows: int = 50) -> dict[str, Any]:
        p = context_dir() / name
        if not p.exists() or "/" in name or name.startswith("."):
            raise HTTPException(404, "no such file")
        if p.suffix == ".csv":
            with p.open(newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
                body = []
                for i, row in enumerate(reader):
                    if i >= rows:
                        break
                    body.append(row)
            total = sum(1 for _ in p.open(encoding="utf-8")) - 1
            return {
                "name": name,
                "kind": "csv",
                "columns": header,
                "rows": body,
                "total_rows": total,
            }
        if p.suffix == ".json":
            data = json.loads(p.read_text())
            if isinstance(data, list):
                return {
                    "name": name,
                    "kind": "json",
                    "records": data[:rows],
                    "total_records": len(data),
                }
            return {"name": name, "kind": "json", "records": [data], "total_records": 1}
        return {"name": name, "kind": "text", "text": p.read_text(encoding="utf-8")}

    # ── agents and runs ──────────────────────────────────────────────────
    @app.get("/api/agents")
    def agents() -> dict[str, Any]:
        reg = read_registry()
        out = []
        for v in list_versions():
            diag = v.path / "diagnosis.json"
            out.append(
                {
                    "name": v.name,
                    "fingerprint": v.fingerprint,
                    "config": v.config.__dict__,
                    "has_helper": v.helper is not None,
                    "helper_functions": re.findall(r"^def (\w+)", v.helper or "", re.M),
                    "diagnosis": json.loads(diag.read_text()) if diag.exists() else None,
                    "runs": [m.run_id for m in list_runs() if m.agent == v.name],
                }
            )
        return {"versions": out, "registry": reg}

    @app.get("/api/agents/diff")
    def agents_diff(a: str, b: str) -> dict[str, Any]:
        """Unified diff of the two surfaces between versions, with the reasoning that produced `b`."""
        import difflib

        try:
            va, vb = load_version(a), load_version(b)
        except FileNotFoundError as e:
            raise HTTPException(404, "no such agent") from e
        fa, fb = va.files(), vb.files()
        files = []
        for name in ("system.md", "helper.py", "agent.yaml"):
            ta, tb = fa.get(name, ""), fb.get(name, "")
            lines = list(
                difflib.unified_diff(
                    ta.splitlines(),
                    tb.splitlines(),
                    fromfile=f"{a}/{name}",
                    tofile=f"{b}/{name}",
                    lineterm="",
                    n=3,
                )
            )
            files.append(
                {
                    "name": name,
                    "changed": ta != tb,
                    "added": sum(1 for ln in lines[2:] if ln.startswith("+")),
                    "removed": sum(1 for ln in lines[2:] if ln.startswith("-")),
                    "diff": lines,
                    "before": ta,
                    "after": tb,
                }
            )
        diag = vb.path / "diagnosis.json"
        diagnosis = json.loads(diag.read_text()) if diag.exists() else None
        change_log: dict[str, Any] | None = None
        if diagnosis and diagnosis.get("changes"):
            change_log = {"source": "in-session", "changes": diagnosis["changes"]}
        elif (vb.path / "change_log.json").exists():
            change_log = json.loads((vb.path / "change_log.json").read_text())
        transcript_path = vb.path / "optimiser_transcript.json"
        closing = None
        if transcript_path.exists():
            prose = [
                m["content"]
                for m in json.loads(transcript_path.read_text())
                if m.get("role") == "assistant"
            ]
            closing = prose[-1] if prose else None
        cycles = [e for e in read_ledger() if e.get("challenger") == b]
        runs_a = [m.__dict__ for m in list_runs() if m.agent == a and m.summary]
        runs_b = [m.__dict__ for m in list_runs() if m.agent == b and m.summary]
        return {
            "a": {"name": a, "fingerprint": va.fingerprint, "runs": runs_a},
            "b": {"name": b, "fingerprint": vb.fingerprint, "runs": runs_b},
            "files": files,
            "diagnosis": diagnosis,
            "change_log": change_log,
            "closing_account": closing,
            "cycles": cycles,
        }

    @app.get("/api/agents/{name}")
    def agent(name: str) -> dict[str, Any]:
        try:
            v = load_version(name)
        except FileNotFoundError as e:
            raise HTTPException(404, "no such agent") from e
        return {
            "name": v.name,
            "fingerprint": v.fingerprint,
            "config": v.config.__dict__,
            "files": v.files(),
        }

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        return [m.__dict__ for m in list_runs()]

    @app.get("/api/runs/{run_id}")
    def run(run_id: str) -> dict[str, Any]:
        try:
            meta, results = load_run(run_id)
        except FileNotFoundError as e:
            raise HTTPException(404, "no such run") from e
        return {"meta": meta.__dict__, "results": [r.__dict__ for r in results]}

    @app.get("/api/runs/{run_id}/traces/{task_id}")
    def trace(run_id: str, task_id: str) -> dict[str, Any]:
        p = RUNS_DIR / run_id / "traces" / f"{task_id}.json"
        if not p.exists():
            raise HTTPException(404, "no trace")
        t = json.loads(p.read_text())
        return {
            **{k: v for k, v in t.items() if k != "trace"},
            "events": trace_events(t),
            "raw": t["trace"],
        }

    @app.get("/api/compare")
    def compare_runs(a: str, b: str) -> dict[str, Any]:
        _, ra = load_run(a)
        _, rb = load_run(b)
        v = compare(ra, rb)
        rows = []
        ma = {r.task_id: r for r in ra}
        mb = {r.task_id: r for r in rb}
        for tid in sorted(set(ma) | set(mb), key=int):
            rows.append(
                {
                    "task_id": tid,
                    "level": (ma.get(tid) or mb.get(tid)).level,  # type: ignore[union-attr]
                    "a": ma[tid].__dict__ if tid in ma else None,
                    "b": mb[tid].__dict__ if tid in mb else None,
                }
            )
        return {"verdict": v.__dict__, "rows": rows}

    @app.get("/api/ledger")
    def ledger() -> list[dict[str, Any]]:
        return read_ledger()

    @app.get("/api/registry")
    def registry() -> dict[str, Any]:
        return read_registry()

    @app.get("/api/experiments")
    def experiments() -> dict[str, Any]:
        return read_snapshot()

    @app.get("/api/demo/pack")
    def demo_pack() -> dict[str, Any]:
        pack = read_pack()
        return {
            "run_id": pack.get("run_id"),
            "agent": pack.get("agent"),
            "model": pack.get("model"),
            "items": [
                {k: v for k, v in it.items() if k != "events"} for it in pack.get("items", [])
            ],
        }

    # ── the live / replayed agent ────────────────────────────────────────
    @app.post("/api/ask")
    async def ask(request: Request) -> EventSourceResponse:
        body = await request.json()
        question = str(body.get("question", "")).strip()
        guidelines = str(body.get("guidelines", "")).strip()
        agent_name = str(
            body.get("agent") or (read_registry().get("champion") or {}).get("agent") or "v0"
        )
        if not question:
            raise HTTPException(400, "question required")
        if s.demo_mode:
            return EventSourceResponse(_replay(question))
        return EventSourceResponse(_live(agent_name, question, guidelines))

    _mount_frontend(app)
    return app


def _task(t: Task) -> dict[str, Any]:
    return {
        "task_id": t.task_id,
        "question": t.question,
        "guidelines": t.guidelines,
        "level": t.level,
        "answer": t.answer,
        "has_gold": t.has_gold,
    }


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


async def _replay(question: str) -> Any:
    pack = read_pack()
    match = next(
        (it for it in pack.get("items", []) if _norm(it["question"]) == _norm(question)), None
    )
    if match is None:
        yield {
            "event": "message",
            "data": json.dumps(
                {
                    "type": "decline",
                    "text": "This is the recorded demo: it replays the champion's answers to the ten dev questions and does not call a model. Pick one of the listed questions.",
                }
            ),
        }
        return
    yield {
        "event": "message",
        "data": json.dumps(
            {
                "type": "start",
                "mode": "replay",
                "run_id": pack.get("run_id"),
                "agent": pack.get("agent"),
                "model": pack.get("model"),
                "task_id": match["task_id"],
                "gold": match["gold"],
                "correct": match["correct"],
            }
        ),
    }
    for ev in match["events"]:
        await asyncio.sleep(0.35 if ev["type"] != "final" else 0.1)
        yield {"event": "message", "data": json.dumps(ev)}


async def _live(agent_name: str, question: str, guidelines: str) -> Any:
    from dabstep_loop.agent.llm import BillingError, require_live
    from dabstep_loop.agent.session import solve_task

    try:
        require_live()
    except BillingError as e:
        yield {"event": "message", "data": json.dumps({"type": "decline", "text": str(e)})}
        return
    version = load_version(agent_name)
    task = Task(task_id="live", question=question, guidelines=guidelines, level="", answer="")
    yield {
        "event": "message",
        "data": json.dumps(
            {
                "type": "start",
                "mode": "live",
                "agent": version.name,
                "fingerprint": version.fingerprint,
                "model": version.config.model,
            }
        ),
    }
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def on_event(ev: dict[str, Any]) -> None:
        queue.put_nowait(ev)

    async def _run() -> None:
        try:
            solve = await solve_task(version, task, on_event=on_event)
            final = trace_events(solve.as_dict())[-1]
            queue.put_nowait(final)
        finally:
            queue.put_nowait(None)

    runner = asyncio.ensure_future(_run())
    while True:
        ev = await queue.get()
        if ev is None:
            break
        yield {"event": "message", "data": json.dumps(ev)}
    await runner


def _wants_document(sec_fetch_dest: str | None, accept: str | None) -> bool:
    if sec_fetch_dest == "document":
        return True
    if sec_fetch_dest:
        return False
    return bool(accept) and "text/html" in str(accept)


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA from this process when `frontend/dist` exists (absent in dev: Vite serves it)."""
    if not FRONTEND_DIST.is_dir():
        return
    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    index = FRONTEND_DIST / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request) -> Any:
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = (FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)
