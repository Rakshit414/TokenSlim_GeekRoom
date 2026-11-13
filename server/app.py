"""TokenSlim FastAPI Web Application & API Gateway.
Geek Room x HackCulture 2026.
"""
import os
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
from dotenv import load_dotenv
import httpx

from server.schemas import RunCreateRequest, RunResponse, HealthResponse, TokenMetrics
from server.database import get_connection, init_db
from server.events import event_bus

# Load environment configuration
load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="TokenSlim",
    description="Autonomous, Token-Efficient Coding Agent with Stale-Answer Detection",
    version="0.1.0",
    lifespan=lifespan
)

@app.get("/")
async def root():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found")
    return FileResponse(index_file)

@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    bifrost_url = os.getenv("BIFROST_BASE_URL", "http://localhost:8080/v1")
    tavily_key = os.getenv("TAVILY_API_KEY", "")

    # Test Bifrost configuration & status
    bifrost_status = "configured" if bifrost_url else "unconfigured"
    bifrost_detail = f"Endpoint configured: {bifrost_url}"
    # If explicitly running live checks, probe socket
    if os.getenv("PROBE_BIFROST_LIVE", "0") == "1":
        try:
            from urllib.parse import urlparse
            import socket
            parsed = urlparse(bifrost_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or (443 if parsed.scheme == "https" else 8080)
            with socket.create_connection((host, port), timeout=0.2):
                bifrost_status = "reachable"
                bifrost_detail = f"Connected to {host}:{port}"
        except Exception as e:
            bifrost_status = "offline"
            bifrost_detail = f"Gateway offline: {e}"

    # Test Tavily configuration
    tavily_status = "configured" if bool(tavily_key) else "missing_api_key"

    # Test SQLite DB
    db_status = "healthy"
    try:
        conn = get_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except Exception as e:
        db_status = f"error: {e}"

    return HealthResponse(
        status="ok",
        version="0.1.0",
        bifrost={
            "url": bifrost_url,
            "status": bifrost_status,
            "detail": bifrost_detail,
            "model": os.getenv("MODEL_NAME", "gpt-4o-mini")
        },
        tavily={
            "status": tavily_status,
            "configured": bool(tavily_key)
        },
        database={
            "status": db_status
        },
        environment=os.getenv("ENVIRONMENT", "development")
    )

@app.post("/api/runs")
async def create_run(request: RunCreateRequest):
    now_iso = datetime.now(timezone.utc).isoformat()
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{os.urandom(3).hex()}"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO runs (run_id, status, configuration, repo_path, prompt, token_budget, is_replay, metrics_json, stale_detections_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        run_id,
        "queued",
        request.configuration,
        request.repo_path,
        request.prompt,
        request.token_budget,
        1 if request.replay else 0,
        json.dumps(TokenMetrics().model_dump()),
        json.dumps([]),
        now_iso
    ))
    conn.commit()
    conn.close()

    return {"run_id": run_id, "status": "queued"}

@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    row = cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return dict(row)

@app.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request):
    queue = event_bus.subscribe(run_id)

    async def event_generator():
        try:
            # Emit initial connection event
            yield {
                "event": "message",
                "data": json.dumps({"type": "log", "source": "GATEWAY", "message": f"Connected to telemetry stream for {run_id}"})
            }
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_data = await asyncio.wait_for(queue.get(), timeout=2.0)
                    yield {
                        "event": "message",
                        "data": json.dumps(event_data)
                    }
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    yield {
                        "event": "ping",
                        "data": ""
                    }
        finally:
            event_bus.unsubscribe(run_id, queue)

    return EventSourceResponse(event_generator())

@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE runs SET status = 'cancelled' WHERE run_id = ?", (run_id,))
    conn.commit()
    conn.close()
    await event_bus.broadcast(run_id, {"type": "log", "source": "SYSTEM", "message": "Run cancelled by user request."})
    return {"status": "cancelled", "run_id": run_id}

@app.get("/api/benchmarks")
async def get_benchmarks():
    results_path = Path(__file__).resolve().parent.parent / "benchmark" / "results.json"
    if results_path.exists():
        with open(results_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"benchmarks": [], "status": "no_results_yet"}

@app.get("/api/traces")
async def get_traces():
    traces_dir = Path(__file__).resolve().parent.parent / "traces"
    traces = []
    if traces_dir.exists():
        for file in traces_dir.glob("*.json*"):
            traces.append(file.name)
    return {"traces": traces}

@app.get("/api/stale-detections")
async def get_stale_detections():
    conn = get_connection()
    cursor = conn.cursor()
    rows = cursor.execute("SELECT run_id, stale_detections_json FROM runs WHERE stale_detections_json != '[]'").fetchall()
    conn.close()
    results = []
    for row in rows:
        dets = json.loads(row["stale_detections_json"])
        for d in dets:
            d["run_id"] = row["run_id"]
            results.append(d)
    return {"stale_detections": results}
