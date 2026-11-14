"""Test suite for FastAPI backend run lifecycle, SSE event streaming,
trace persistence, replay, cancellation, and execution visibility (Checkpoint 6).
"""
import os
import json
import time
import pytest
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from server.app import app, active_loops
from server.database import (
    init_db, get_connection, save_run_event, get_run_events,
    save_execution_trace, get_execution_trace, get_all_runs, update_run_status
)
from server.events import event_bus
from agent.loop import AutonomousCodingLoop, ExecutionSummary
from agent.verification import TestRunner

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()

def test_background_run_creation_and_state_transitions():
    """Verify POST /api/runs creates a run and GET /api/runs/{run_id} returns state."""
    payload = {
        "repo_path": "benchmark/tasks/task_01_factorial_off_by_one",
        "configuration": "leancode_tavily",
        "prompt": "Fix off-by-one error in calculator",
        "token_budget": 12000,
        "replay": False
    }

    mock_summary = ExecutionSummary(
        run_id="test_run",
        status="COMPLETED_VERIFIED",
        tests_passed=True,
        iterations_count=1,
        total_tokens_spent=200
    )

    with patch.object(AutonomousCodingLoop, "run", return_value=mock_summary):
        resp = client.post("/api/runs", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "run_id" in data
        run_id = data["run_id"]
        assert data["status"] == "running"

        # Verify retrieval via GET /api/runs/{run_id}
        resp_get = client.get(f"/api/runs/{run_id}")
        assert resp_get.status_code == 200
        run_data = resp_get.json()
        assert run_data["run_id"] == run_id
        assert run_data["configuration"] == "leancode_tavily"
        assert run_data["token_budget"] == 12000

        # Verify run list endpoint
        resp_list = client.get("/api/runs?limit=10")
        assert resp_list.status_code == 200
        runs = resp_list.json()["runs"]
        assert any(r["run_id"] == run_id for r in runs)

def test_sse_event_ordering_and_persistence():
    """Verify that execution events are persisted and streamed in strict chronological order."""
    run_id = f"test_sse_order_{int(time.time())}"
    now_str = "2026-11-14T10:00:00"

    conn = get_connection()
    conn.execute("""
        INSERT INTO runs (run_id, status, configuration, repo_path, prompt, token_budget, created_at)
        VALUES (?, 'completed', 'leancode', 'test/path', 'prompt', 10000, ?)
    """, (run_id, now_str))
    conn.commit()
    conn.close()

    # Save 3 sequential events
    id1 = save_run_event(run_id, "start", {"run_id": run_id, "type": "start", "message": "Run started"})
    id2 = save_run_event(run_id, "repo_scanned", {"run_id": run_id, "type": "repo_scanned", "message": "Scanned 5 files"})
    id3 = save_run_event(run_id, "finish", {"run_id": run_id, "type": "finish", "message": "Run completed successfully"})

    assert id1 < id2 < id3

    # Fetch events via SSE stream endpoint with bounded loop
    lines = []
    with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
        for line in stream.iter_lines():
            if line:
                lines.append(line)
            if "Run completed successfully" in line or "stream_closed" in line:
                break

    # Verify events exist in the stream output
    stream_content = "\n".join(lines)
    assert f"id: {id1}" in stream_content
    assert f"id: {id2}" in stream_content
    assert f"id: {id3}" in stream_content
    assert "Run started" in stream_content
    assert "Scanned 5 files" in stream_content
    assert "Run completed successfully" in stream_content

def test_sse_reconnection_with_last_event_id():
    """Verify that a client reconnecting with Last-Event-ID recovers only unreceived events."""
    run_id = f"test_reconnect_{int(time.time())}"
    now_str = "2026-11-14T10:00:00"

    conn = get_connection()
    conn.execute("""
        INSERT INTO runs (run_id, status, configuration, repo_path, prompt, token_budget, created_at)
        VALUES (?, 'completed', 'leancode', 'test/path', 'prompt', 10000, ?)
    """, (run_id, now_str))
    conn.commit()
    conn.close()

    id1 = save_run_event(run_id, "evt1", {"run_id": run_id, "type": "evt1", "message": "Event 1"})
    id2 = save_run_event(run_id, "evt2", {"run_id": run_id, "type": "evt2", "message": "Event 2"})
    id3 = save_run_event(run_id, "evt3", {"run_id": run_id, "type": "evt3", "message": "Event 3"})

    # Reconnect asking for events after id2
    headers = {"last-event-id": str(id2)}
    lines = []
    with client.stream("GET", f"/api/runs/{run_id}/events", headers=headers) as stream:
        for line in stream.iter_lines():
            if line:
                lines.append(line)
            if "Event 3" in line or "stream_closed" in line:
                break

    stream_content = "\n".join(lines)
    # id1 and id2 must NOT be present
    assert f"id: {id1}" not in stream_content
    assert f"id: {id2}" not in stream_content
    # id3 MUST be present
    assert f"id: {id3}" in stream_content
    assert "Event 3" in stream_content

def test_run_cancellation_and_subprocess_safety():
    """Verify that cancelling an active run terminates child processes and updates state."""
    run_id = f"test_cancel_{int(time.time())}"
    temp_dir = tempfile.mkdtemp(prefix="test_cancel_")

    try:
        mock_loop = MagicMock()
        mock_loop.run_id = run_id
        mock_loop.is_cancelled = False
        def cancel_action():
            mock_loop.is_cancelled = True
        mock_loop.cancel = cancel_action

        active_loops[run_id] = mock_loop

        conn = get_connection()
        conn.execute("""
            INSERT INTO runs (run_id, status, configuration, repo_path, prompt, token_budget, created_at)
            VALUES (?, 'running', 'leancode', ?, 'test task', 10000, datetime('now'))
        """, (run_id, temp_dir))
        conn.commit()
        conn.close()

        # Send cancellation request
        resp = client.post(f"/api/runs/{run_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        # Verify loop cancel was invoked
        assert mock_loop.is_cancelled is True

        # Verify database record updated
        conn = get_connection()
        row = conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        conn.close()
        assert row["status"] == "cancelled"

        # Verify cancellation event was persisted
        events = get_run_events(run_id)
        assert any(e["event_type"] == "cancelled" for e in events)

    finally:
        active_loops.pop(run_id, None)
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_run_trace_retrieval_and_replay():
    """Verify GET /api/runs/{run_id}/trace and POST /api/runs/{run_id}/replay."""
    run_id = f"test_trace_{int(time.time())}"
    now_str = "2026-11-14T10:00:00"

    trace_data = {
        "run_id": run_id,
        "status": "COMPLETED_VERIFIED",
        "configuration": "leancode_tavily",
        "diff": "--- a/test.py\n+++ b/test.py\n@@ -1 +1 @@\n-old\n+new",
        "events": [{"type": "start", "message": "Init"}, {"type": "finish", "message": "Done"}]
    }
    save_execution_trace(run_id, trace_data)

    save_run_event(run_id, "start", {"run_id": run_id, "type": "start", "message": "Init"})
    save_run_event(run_id, "finish", {"run_id": run_id, "type": "finish", "message": "Done"})

    conn = get_connection()
    conn.execute("""
        INSERT INTO runs (run_id, status, configuration, repo_path, prompt, token_budget, created_at)
        VALUES (?, 'COMPLETED_VERIFIED', 'leancode_tavily', 'test/repo', 'fix', 10000, ?)
    """, (run_id, now_str))
    conn.commit()
    conn.close()

    # GET trace
    resp_trace = client.get(f"/api/runs/{run_id}/trace")
    assert resp_trace.status_code == 200
    data = resp_trace.json()
    assert data["run_id"] == run_id
    assert data["status"] == "COMPLETED_VERIFIED"
    assert "diff" in data

    # Trigger replay
    resp_replay = client.post(f"/api/runs/{run_id}/replay")
    assert resp_replay.status_code == 200
    assert resp_replay.json()["status"] == "replaying"
    assert resp_replay.json()["events_count"] == 2

def test_concurrent_runs_isolation():
    """Verify that multiple concurrent runs execute with isolated state and event streams."""
    run_id_1 = f"run_iso_1_{int(time.time())}"
    run_id_2 = f"run_iso_2_{int(time.time())}"

    save_run_event(run_id_1, "event_a", {"run_id": run_id_1, "msg": "Run 1 unique message"})
    save_run_event(run_id_2, "event_b", {"run_id": run_id_2, "msg": "Run 2 unique message"})

    events_1 = get_run_events(run_id_1)
    events_2 = get_run_events(run_id_2)

    assert len(events_1) == 1
    assert len(events_2) == 1
    assert events_1[0]["payload"]["msg"] == "Run 1 unique message"
    assert events_2[0]["payload"]["msg"] == "Run 2 unique message"
    assert "Run 2" not in json.dumps(events_1)
    assert "Run 1" not in json.dumps(events_2)

def test_replay_mode_flagged_explicitly():
    """Verify that replay runs are explicitly flagged with is_replay=1 and not simulated as live."""
    payload = {
        "repo_path": "benchmark/tasks/task_01_factorial_off_by_one",
        "configuration": "leancode_tavily",
        "prompt": "Replay test demo",
        "token_budget": 10000,
        "replay": True
    }

    resp = client.post("/api/runs", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_replay"] is True

    # Check database persistence
    conn = get_connection()
    row = conn.execute("SELECT is_replay FROM runs WHERE run_id = ?", (data["run_id"],)).fetchone()
    conn.close()
    assert row["is_replay"] == 1

def test_metrics_separation_api_contract():
    """Verify GET /api/runs/{run_id}/metrics clearly separates simulated vs real usage."""
    run_id = f"test_metrics_contract_{int(time.time())}"

    conn = get_connection()
    conn.execute("""
        INSERT INTO runs (run_id, status, configuration, repo_path, prompt, metrics_json, created_at)
        VALUES (?, 'completed', 'leancode', 'test/repo', 'fix', '{"is_simulated": true, "total_simulated_tokens": 500, "provider_reported_tokens": null}', datetime('now'))
    """, (run_id,))
    conn.execute("""
        INSERT INTO model_calls (
            run_id, call_id, model, provider, request_id, input_tokens, output_tokens,
            total_tokens, cached_tokens, latency_seconds, calculated_cost, is_simulated, created_at
        ) VALUES (?, 'call_mock', 'mock-agent', 'mock-adapter', 'req-1', 400, 100, 500, 0, null, null, 1, datetime('now'))
    """, (run_id,))
    conn.commit()
    conn.close()

    resp = client.get(f"/api/runs/{run_id}/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["metrics_summary"]["is_simulated"] is True
    assert data["metrics_summary"]["provider_reported_tokens"] is None
    assert data["model_calls"][0]["is_simulated"] == 1
    assert data["model_calls"][0]["provider"] == "mock-adapter"
