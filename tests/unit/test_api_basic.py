from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zem.api import data_source
from zem.api.app import app
from zem.audit.store import SqliteAudit
from zem.contracts.models import (
    AuditEvent,
    Decision,
    FinalDecision,
    ToolCallContext,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _sample_event(seq: int = 1, call_id: str = "call_test_1") -> AuditEvent:
    ctx = ToolCallContext(
        call_id=call_id,
        session_id="sess_1",
        ts=datetime.now(UTC),
        server="test_srv",
        tool="test_tool",
        arguments={"param": "value"},
        signals=[],
    )
    return AuditEvent(
        seq=seq,
        ts=ctx.ts,
        session_id="sess_1",
        call_id=call_id,
        context=ctx,
        final=FinalDecision(decision=Decision.ALLOW, risk=0.1, reasons=[]),
        latency_breakdown_ms={"pipeline": 5},
    )


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_decisions_success(client: TestClient) -> None:
    response = client.get("/api/decisions")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if len(data) > 0:
        first = data[0]
        # Must match AuditEvent schema fields
        assert "seq" in first
        assert "call_id" in first
        assert "session_id" in first
        assert "context" in first
        assert "final" in first


def test_get_decisions_limit(client: TestClient) -> None:
    response = client.get("/api/decisions?limit=2")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) <= 2


def test_get_decisions_newest_first(client: TestClient) -> None:
    response = client.get("/api/decisions?limit=10")
    assert response.status_code == 200
    data = response.json()
    if len(data) >= 2:
        for i in range(len(data) - 1):
            assert data[i]["ts"] >= data[i + 1]["ts"]


def test_get_decisions_missing_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing_file = tmp_path / "does_not_exist.json"
    missing_db = tmp_path / "does_not_exist.db"
    monkeypatch.setattr(data_source, "DEFAULT_FAKE_EVENTS_PATH", missing_file)
    monkeypatch.setattr(data_source, "DEFAULT_DB_PATH", missing_db)

    response = client.get("/api/decisions")
    assert response.status_code == 200
    assert response.json() == []


def test_get_decisions_corrupted_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    corrupted_file = tmp_path / "broken.json"
    corrupted_file.write_text("NOT_JSON{{{", encoding="utf-8")
    missing_db = tmp_path / "does_not_exist.db"
    monkeypatch.setattr(data_source, "DEFAULT_FAKE_EVENTS_PATH", corrupted_file)
    monkeypatch.setattr(data_source, "DEFAULT_DB_PATH", missing_db)

    response = client.get("/api/decisions")
    assert response.status_code == 200
    assert response.json() == []


def test_cors_headers(client: TestClient) -> None:
    headers = {"Origin": "http://localhost:5173"}
    response = client.get("/healthz", headers=headers)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_read_only_routes(client: TestClient) -> None:
    post_res = client.post("/api/decisions", json={"foo": "bar"})
    assert post_res.status_code == 405

    delete_res = client.delete("/api/decisions")
    assert delete_res.status_code == 405


def test_get_decision_by_id_found(client: TestClient) -> None:
    list_res = client.get("/api/decisions?limit=1")
    decisions = list_res.json()
    if decisions:
        call_id = decisions[0]["call_id"]
        res = client.get(f"/api/decisions/{call_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["call_id"] == call_id
        assert "context" in data


def test_get_decision_by_id_not_found(client: TestClient) -> None:
    res = client.get("/api/decisions/call_nonexistent_9999999999")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_sqlite_integration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_file = tmp_path / "test_zem.db"
    monkeypatch.setattr(data_source, "DEFAULT_DB_PATH", db_file)

    store = SqliteAudit(db_file)
    ev1 = _sample_event(seq=1, call_id="call_sql_1")
    ev2 = _sample_event(seq=2, call_id="call_sql_2")
    store.append(ev1)
    store.append(ev2)

    # Test get_decisions from SQLite
    res = client.get("/api/decisions?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    # Newest first
    assert data[0]["call_id"] == "call_sql_2"
    assert data[1]["call_id"] == "call_sql_1"

    # Test get_decision_by_id from SQLite
    res_single = client.get("/api/decisions/call_sql_1")
    assert res_single.status_code == 200
    assert res_single.json()["call_id"] == "call_sql_1"


def test_stream_endpoint_connection(client: TestClient) -> None:
    # Use limit=0 to test connection handshake and immediate clean termination
    with client.stream("GET", "/api/stream?limit=0") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        lines = [line for line in response.iter_lines() if line]
        assert any("connected" in l for l in lines)


def test_stream_delivers_new_events(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_file = tmp_path / "stream_test.db"
    monkeypatch.setattr(data_source, "DEFAULT_DB_PATH", db_file)

    store = SqliteAudit(db_file)
    ev = _sample_event(seq=1, call_id="call_stream_1")
    store.append(ev)

    # Request stream starting after seq=0 with limit=1 to receive the decision event
    with client.stream("GET", "/api/stream?after_seq=0&limit=1") as response:
        assert response.status_code == 200
        captured_data = [line for line in response.iter_lines() if line.startswith("data:")]
        assert len(captured_data) >= 2
        # Verify the decision payload is streamed
        assert any("call_stream_1" in d for d in captured_data)
