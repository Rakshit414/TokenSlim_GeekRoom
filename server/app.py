"""TokenSlim FastAPI Web Application & API Gateway.
Geek Room x HackCulture 2026.
"""
import os
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from dotenv import load_dotenv
import httpx

from server.schemas import RunCreateRequest, RunResponse, HealthResponse, TokenMetrics
from server.database import (
    get_connection, init_db, save_stale_detection_run,
    get_stale_detection_run, get_claims_for_run,
    get_evidence_for_claim, get_correction_for_claim,
    save_run_event, get_run_events, save_execution_trace,
    get_execution_trace, get_all_runs, update_run_status
)
from server.events import event_bus
from agent.loop import AutonomousCodingLoop, ExecutionSummary
from agent.stale_detector import StaleAnswerDetector

# Static asset directory
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Active loop registry for cancellation
active_loops: Dict[str, AutonomousCodingLoop] = {}

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

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

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

    # Bifrost status: configured | reachable | unreachable | not_verified
    if not bifrost_url:
        bifrost_status = "unconfigured"
        bifrost_detail = "BIFROST_BASE_URL is not set"
    elif os.getenv("PROBE_BIFROST_LIVE", "0") == "1":
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
            bifrost_status = "unreachable"
            bifrost_detail = f"Connection failed: {e}"
    else:
        # Avoid blocking network probes in offline / sandboxed test mode
        bifrost_status = "not_verified"
        bifrost_detail = f"Configured endpoint {bifrost_url}; live network probe disabled (PROBE_BIFROST_LIVE!=1)"

    # Tavily status: configured | reachable | unreachable | not_verified
    if not tavily_key or not tavily_key.strip():
        tavily_status = "unconfigured"
        tavily_detail = "TAVILY_API_KEY is not set"
    elif os.getenv("PROBE_TAVILY_LIVE", "0") == "1":
        try:
            import httpx
            # Simple probe
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get("https://api.tavily.com")
                if resp.status_code < 500:
                    tavily_status = "reachable"
                    tavily_detail = "Tavily API endpoint reached"
                else:
                    tavily_status = "unreachable"
                    tavily_detail = f"Tavily returned HTTP {resp.status_code}"
        except Exception as e:
            tavily_status = "unreachable"
            tavily_detail = f"Tavily connection failed: {e}"
    else:
        tavily_status = "not_verified"
        tavily_detail = "TAVILY_API_KEY present; live network probe disabled (PROBE_TAVILY_LIVE!=1)"

    # SQLite status: available | unavailable
    db_status = "available"
    db_detail = "SQLite connection operational"
    try:
        conn = get_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except Exception as e:
        db_status = "unavailable"
        db_detail = f"SQLite failure: {e}"

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
            "detail": tavily_detail,
            "configured": bool(tavily_key and tavily_key.strip())
        },
        database={
            "status": db_status,
            "detail": db_detail
        },
        environment=os.getenv("ENVIRONMENT", "development")
    )

@app.get("/api/runs")
async def list_runs(limit: int = 50):
    """Retrieve recent autonomous agent runs."""
    return {"runs": get_all_runs(limit=limit)}

@app.post("/api/runs")
async def create_run(request: RunCreateRequest):
    now_iso = datetime.now(timezone.utc).isoformat()
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{os.urandom(3).hex()}"

    # Check if target repository exists
    target_repo = request.repo_path
    if not Path(target_repo).is_absolute():
        target_repo = str((Path(__file__).resolve().parent.parent / target_repo).resolve())

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO runs (run_id, status, configuration, repo_path, prompt, token_budget, is_replay, metrics_json, stale_detections_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        run_id,
        "running",
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

    # Record initial run_created event
    init_evt = {
        "run_id": run_id,
        "type": "state_change",
        "message": f"Run {run_id} initialized in '{request.configuration}' mode.",
        "data": {
            "status": "running",
            "is_replay": bool(request.replay),
            "configuration": request.configuration
        },
        "timestamp": datetime.now(timezone.utc).timestamp()
    }
    save_run_event(run_id, "state_change", init_evt)

    # Replay mode handler
    if request.replay:
        async def execute_replay():
            demo_trace_file = Path(__file__).resolve().parent.parent / "traces" / "demo_pydantic_v2_migration.json"
            trace_events = []
            if demo_trace_file.exists():
                try:
                    with open(demo_trace_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        trace_events = data.get("events", [])
                except Exception:
                    pass

            for evt in trace_events:
                if run_id not in active_loops:
                    break
                evt_copy = dict(evt)
                evt_copy["run_id"] = run_id
                evt_copy["is_replay"] = True
                evt_id = save_run_event(run_id, evt_copy.get("type", "log"), evt_copy)
                evt_copy["id"] = evt_id
                await event_bus.broadcast(run_id, evt_copy)
                await asyncio.sleep(0.08)

            update_run_status(run_id, "completed", completed_at=datetime.now(timezone.utc).isoformat())
            active_loops.pop(run_id, None)

        active_loops[run_id] = "replay"
        asyncio.create_task(execute_replay())
        return {"run_id": run_id, "status": "running", "is_replay": True}

    # Live execution loop
    loop_instance = AutonomousCodingLoop(
        workspace_dir=target_repo,
        task_directive=request.prompt or "Analyze repository and repair defects",
        token_budget=request.token_budget or 15000,
        configuration=request.configuration,
        run_id=run_id
    )
    active_loops[run_id] = loop_instance

    async def execute_background():
        try:
            summary = await asyncio.to_thread(loop_instance.run)
            # Emit final metrics event
            await event_bus.broadcast(run_id, {
                "id": len(summary.events_log) + 1,
                "run_id": run_id,
                "type": "metrics",
                "message": f"Final metrics: {summary.total_tokens_spent} tokens spent, {summary.iterations_count} iteration(s).",
                "data": {
                    "total_tokens": summary.total_tokens_spent,
                    "provider_tokens": summary.provider_reported_tokens,
                    "estimated_context_tokens": summary.estimated_context_tokens,
                    "llm_calls": summary.iterations_count,
                    "tests_passed": summary.tests_passed,
                    "is_simulated": summary.is_simulated
                },
                "timestamp": datetime.now(timezone.utc).timestamp()
            })
            if summary.diffs:
                await event_bus.broadcast(run_id, {
                    "id": len(summary.events_log) + 2,
                    "run_id": run_id,
                    "type": "diff",
                    "message": "Final unified diff generated.",
                    "data": {"diff": "\n".join(summary.diffs)},
                    "timestamp": datetime.now(timezone.utc).timestamp()
                })
        except Exception as e:
            update_run_status(run_id, "failed", completed_at=datetime.now(timezone.utc).isoformat())
            err_evt = {
                "run_id": run_id,
                "type": "log",
                "message": f"Execution loop failed: {e}",
                "data": {"error": str(e)},
                "timestamp": datetime.now(timezone.utc).timestamp()
            }
            save_run_event(run_id, "log", err_evt)
            await event_bus.broadcast(run_id, err_evt)
        finally:
            active_loops.pop(run_id, None)

    asyncio.create_task(execute_background())
    return {"run_id": run_id, "status": "running", "is_replay": False}

@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    row = cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return dict(row)

@app.get("/api/runs/{run_id}/trace")
async def get_run_trace_api(run_id: str):
    trace = get_execution_trace(run_id)
    if trace:
        return trace

    conn = get_connection()
    cursor = conn.cursor()
    run_row = cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    conn.close()
    if not run_row:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    events = get_run_events(run_id)
    return {
        "run_id": run_id,
        "status": run_row["status"],
        "configuration": run_row["configuration"],
        "repo_path": run_row["repo_path"],
        "prompt": run_row["prompt"],
        "metrics": json.loads(run_row["metrics_json"] or "{}"),
        "diff": run_row["diff_text"] or "",
        "events": events
    }

@app.post("/api/runs/{run_id}/replay")
async def trigger_run_replay(run_id: str):
    events = get_run_events(run_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"No events found to replay for run '{run_id}'")

    async def replay_events():
        for evt in events:
            payload = evt.get("payload") or {}
            payload["is_replay"] = True
            await event_bus.broadcast(run_id, payload)
            await asyncio.sleep(0.05)

    asyncio.create_task(replay_events())
    return {"status": "replaying", "run_id": run_id, "events_count": len(events)}

@app.get("/api/runs/{run_id}/metrics")
async def get_run_metrics(run_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    run_row = cursor.execute("SELECT run_id, status, metrics_json, created_at, completed_at FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if not run_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Run not found")

    calls_rows = cursor.execute("SELECT * FROM model_calls WHERE run_id = ? ORDER BY id ASC", (run_id,)).fetchall()
    conn.close()

    calls = [dict(c) for c in calls_rows]
    metrics_summary = json.loads(run_row["metrics_json"] or "{}")

    return {
        "run_id": run_id,
        "status": run_row["status"],
        "metrics_summary": metrics_summary,
        "model_calls": calls,
        "total_calls": len(calls)
    }

@app.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request):
    last_event_id_header = request.headers.get("last-event-id") or request.query_params.get("last_event_id")
    after_id = 0
    if last_event_id_header:
        try:
            after_id = int(last_event_id_header)
        except ValueError:
            after_id = 0

    queue = event_bus.subscribe(run_id)

    async def event_generator():
        try:
            # 1. Deliver historical / missed events from database first
            historical_events = get_run_events(run_id, after_id=after_id)
            for h_evt in historical_events:
                payload = h_evt.get("payload") or {}
                evt_type = payload.get("type", h_evt.get("event_type", "message"))
                yield {
                    "id": str(h_evt["id"]),
                    "event": evt_type,
                    "data": json.dumps(payload)
                }

            # Check if run is already finished and no active loop
            conn = get_connection()
            cursor = conn.cursor()
            run_row = cursor.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            conn.close()

            is_already_terminal = run_row and run_row["status"] in ("completed", "cancelled", "failed", "COMPLETED_VERIFIED", "MAX_ITERATIONS_REACHED")
            if is_already_terminal and run_id not in active_loops:
                yield {
                    "id": str(historical_events[-1]["id"] + 1) if historical_events else "1",
                    "event": "stream_closed",
                    "data": json.dumps({"status": run_row["status"], "message": f"Run {run_id} is in terminal state."})
                }
                return

            # 2. Stream live events as they occur
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_data = await asyncio.wait_for(queue.get(), timeout=2.0)
                    evt_id = str(event_data.get("id") or "")
                    evt_type = event_data.get("type", "message")
                    yield {
                        "id": evt_id,
                        "event": evt_type,
                        "data": json.dumps(event_data)
                    }

                    if evt_type in ("finish", "cancelled", "timeout", "failed"):
                        break
                except asyncio.TimeoutError:
                    # Heartbeat comment to keep SSE connection alive
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps({"timestamp": datetime.now(timezone.utc).timestamp()})
                    }
        finally:
            event_bus.unsubscribe(run_id, queue)

    return EventSourceResponse(event_generator())

@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    loop = active_loops.get(run_id)
    if loop and hasattr(loop, "cancel"):
        loop.cancel()

    update_run_status(run_id, "cancelled", completed_at=datetime.now(timezone.utc).isoformat())

    cancel_evt = {
        "run_id": run_id,
        "type": "cancelled",
        "message": "Run cancelled by user request.",
        "data": {"status": "cancelled"},
        "timestamp": datetime.now(timezone.utc).timestamp()
    }
    evt_id = save_run_event(run_id, "cancelled", cancel_evt)
    cancel_evt["id"] = evt_id
    await event_bus.broadcast(run_id, cancel_evt)
    return {"status": "cancelled", "run_id": run_id}

@app.get("/api/benchmarks")
async def get_benchmarks():
    results_path = Path(__file__).resolve().parent.parent / "benchmark" / "results.json"
    if results_path.exists():
        with open(results_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"benchmarks": [], "status": "no_results_yet"}

class BenchmarkRunRequest(BaseModel):
    task_ids: Optional[List[str]] = None
    configurations: Optional[List[str]] = None
    use_deterministic_mocks: Optional[bool] = True

@app.post("/api/benchmarks/run")
async def trigger_benchmark_api(request: BenchmarkRunRequest = BenchmarkRunRequest()):
    from benchmark.runner import BenchmarkRunner, TASKS_DIR
    runner = BenchmarkRunner(
        tasks_dir=TASKS_DIR,
        use_deterministic_mocks=request.use_deterministic_mocks if request.use_deterministic_mocks is not None else True
    )
    summary = await asyncio.to_thread(
        runner.run_suite,
        task_ids=request.task_ids,
        configurations=request.configurations,
        save_results=True
    )
    return summary.model_dump()

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

class StaleDetectionRunRequest(BaseModel):
    task: str = "Technical verification"
    code_snippets: Optional[Dict[str, str]] = None
    claims: Optional[List[Dict[str, Any]]] = None
    max_searches: Optional[int] = 5

@app.post("/api/stale-detection/runs")
async def run_stale_detection_api(request: StaleDetectionRunRequest):
    detector = StaleAnswerDetector(search_budget=request.max_searches or 5)
    run = detector.run_detection(
        task=request.task,
        code_snippets=request.code_snippets,
        explicit_claims=request.claims,
        max_searches=request.max_searches,
        persist=True
    )
    return {
        "run_id": run.run_id,
        "status": run.status,
        "task_description": run.task_description,
        "total_claims": len(run.claims),
        "stale_count": len(run.stale_claims),
        "current_count": len(run.current_claims),
        "uncertain_count": len(run.uncertain_claims),
        "searches_executed": run.searches_executed,
        "is_simulated": run.is_simulated,
        "claims": [c.model_dump() for c in run.claims]
    }

@app.get("/api/stale-detection/runs/{run_id}")
async def get_stale_run_api(run_id: str):
    run = get_stale_detection_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Stale detection run '{run_id}' not found")
    claims = get_claims_for_run(run_id)
    return {
        "run": run,
        "claims": claims
    }

@app.get("/api/stale-detection/runs/{run_id}/claims")
async def get_run_claims_api(run_id: str):
    claims = get_claims_for_run(run_id)
    return {"run_id": run_id, "claims": claims}

@app.get("/api/stale-detection/claims/{claim_id}/evidence")
async def get_claim_evidence_api(claim_id: str):
    evidence = get_evidence_for_claim(claim_id)
    return {"claim_id": claim_id, "evidence": evidence}

@app.get("/api/stale-detection/claims/{claim_id}/correction")
async def get_claim_correction_api(claim_id: str):
    corr = get_correction_for_claim(claim_id)
    if not corr:
        raise HTTPException(status_code=404, detail=f"Claim '{claim_id}' not found")
    return corr
