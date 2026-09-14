"""The read routes serve the committed files; `/api/ask` never reaches a model in demo mode."""

import json

import pytest
from fastapi.testclient import TestClient

from dabstep_loop.serving.app import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DEMO_MODE", "1")
    return TestClient(create_app())


def test_health_reports_demo_and_champion(client: TestClient) -> None:
    body = client.get("/healthz").json()
    assert body["mode"] == "demo"
    assert body["champion"] and body["champion"].startswith("v")


def test_tasks_and_data(client: TestClient) -> None:
    assert len(client.get("/api/tasks?split=all").json()) == 450
    dev = client.get("/api/tasks?split=dev").json()
    assert len(dev) == 10 and all(t["has_gold"] for t in dev)
    files = client.get("/api/data/files").json()
    assert {f["name"] for f in files["files"]} >= {"payments.csv", "fees.json", "manual.md"}
    fees = client.get("/api/data/files/fees.json?rows=3").json()
    assert fees["kind"] == "json" and fees["total_records"] == 1000 and len(fees["records"]) == 3
    assert client.get("/api/data/files/../pyproject.toml").status_code == 404


def test_runs_agents_ledger(client: TestClient) -> None:
    runs = client.get("/api/runs").json()
    assert runs, "a committed run is required"
    run = client.get(f"/api/runs/{runs[0]['run_id']}").json()
    assert run["meta"]["run_id"] == runs[0]["run_id"] and run["results"]
    agents = client.get("/api/agents").json()
    assert any(v["name"] == "v0" for v in agents["versions"])
    assert "system.md" in client.get("/api/agents/v0").json()["files"]
    assert isinstance(client.get("/api/ledger").json(), list)


def test_ask_in_demo_mode_declines_unknown_questions(client: TestClient) -> None:
    with client.stream("POST", "/api/ask", json={"question": "what is the meaning of life"}) as r:
        text = "".join(r.iter_text())
    events = [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]
    assert events and events[0]["type"] == "decline"
