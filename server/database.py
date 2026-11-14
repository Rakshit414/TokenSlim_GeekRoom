"""SQLite database storage for TokenSlim execution runs, events, and benchmarks."""
import sqlite3
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

DB_PATH = Path(__file__).resolve().parent.parent / "tokenslim.db"

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
    except Exception:
        pass
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            configuration TEXT NOT NULL,
            repo_path TEXT NOT NULL,
            prompt TEXT,
            token_budget INTEGER,
            is_replay INTEGER DEFAULT 0,
            metrics_json TEXT,
            stale_detections_json TEXT,
            diff_text TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs (run_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS benchmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            configuration TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            passed INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            call_id TEXT NOT NULL,
            model TEXT NOT NULL,
            provider TEXT NOT NULL,
            request_id TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            total_tokens INTEGER,
            cached_tokens INTEGER,
            latency_seconds REAL,
            calculated_cost REAL,
            is_simulated INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs (run_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stale_detection_runs (
            run_id TEXT PRIMARY KEY,
            task_description TEXT,
            status TEXT NOT NULL,
            total_claims INTEGER DEFAULT 0,
            stale_count INTEGER DEFAULT 0,
            current_count INTEGER DEFAULT 0,
            uncertain_count INTEGER DEFAULT 0,
            searches_executed INTEGER DEFAULT 0,
            search_budget INTEGER DEFAULT 5,
            is_simulated INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS detection_claims (
            claim_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            claim_text TEXT NOT NULL,
            technology TEXT,
            version TEXT,
            file_path TEXT,
            line_start INTEGER,
            line_end INTEGER,
            priority TEXT DEFAULT 'medium',
            classification TEXT DEFAULT 'UNCERTAIN',
            confidence REAL DEFAULT 0.0,
            reasoning TEXT,
            recommended_correction TEXT,
            suggested_patch TEXT,
            is_simulated INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES stale_detection_runs (run_id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_detection_claims_run ON detection_claims(run_id)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS claim_evidence (
            evidence_id TEXT PRIMARY KEY,
            claim_id TEXT NOT NULL,
            url TEXT NOT NULL,
            domain TEXT,
            title TEXT,
            excerpt TEXT,
            relevance_score REAL DEFAULT 0.0,
            retrieved_at TEXT NOT NULL,
            is_simulated INTEGER DEFAULT 0,
            FOREIGN KEY (claim_id) REFERENCES detection_claims (claim_id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_claim_evidence_claim ON claim_evidence(claim_id)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS execution_traces (
            run_id TEXT PRIMARY KEY,
            trace_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs (run_id)
        )
    """)
    conn.commit()
    conn.close()

def save_stale_detection_run(
    run_id: str,
    task_description: str,
    status: str,
    claims: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    searches_executed: int = 0,
    search_budget: int = 5,
    is_simulated: bool = False
):
    """Persist a complete stale detection run with claims and evidence."""
    conn = get_connection()
    cursor = conn.cursor()

    stale_count = sum(1 for c in claims if c.get("classification") == "STALE")
    current_count = sum(1 for c in claims if c.get("classification") == "CURRENT")
    uncertain_count = sum(1 for c in claims if c.get("classification") == "UNCERTAIN")
    now_str = datetime.now().isoformat()

    cursor.execute("""
        INSERT INTO stale_detection_runs (
            run_id, task_description, status, total_claims, stale_count, current_count,
            uncertain_count, searches_executed, search_budget, is_simulated, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            status = excluded.status,
            total_claims = excluded.total_claims,
            stale_count = excluded.stale_count,
            current_count = excluded.current_count,
            uncertain_count = excluded.uncertain_count,
            searches_executed = excluded.searches_executed,
            is_simulated = excluded.is_simulated
    """, (
        run_id, task_description, status, len(claims), stale_count, current_count,
        uncertain_count, searches_executed, search_budget, 1 if is_simulated else 0, now_str
    ))

    for c in claims:
        cursor.execute("""
            INSERT INTO detection_claims (
                claim_id, run_id, claim_text, technology, version, file_path, line_start,
                line_end, priority, classification, confidence, reasoning,
                recommended_correction, suggested_patch, is_simulated, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(claim_id) DO UPDATE SET
                classification = excluded.classification,
                confidence = excluded.confidence,
                reasoning = excluded.reasoning,
                recommended_correction = excluded.recommended_correction,
                suggested_patch = excluded.suggested_patch,
                is_simulated = excluded.is_simulated
        """, (
            c["claim_id"], run_id, c["claim_text"], c.get("technology"), c.get("version"),
            c.get("file_path"), c.get("line_start"), c.get("line_end"),
            c.get("priority", "medium"), c.get("classification", "UNCERTAIN"),
            c.get("confidence", 0.0), c.get("reasoning", ""),
            c.get("recommended_correction"), c.get("suggested_patch"),
            1 if c.get("is_simulated", False) else 0, c.get("created_at", now_str)
        ))

    for ev in evidence_records:
        cursor.execute("""
            INSERT INTO claim_evidence (
                evidence_id, claim_id, url, domain, title, excerpt, relevance_score,
                retrieved_at, is_simulated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(evidence_id) DO UPDATE SET
                relevance_score = excluded.relevance_score,
                excerpt = excluded.excerpt
        """, (
            ev["evidence_id"], ev["claim_id"], ev["url"], ev.get("domain", ""),
            ev.get("title", ""), ev.get("excerpt", ""), ev.get("relevance_score", 0.0),
            ev.get("retrieved_at", now_str), 1 if ev.get("is_simulated", False) else 0
        ))

    conn.commit()
    conn.close()

def get_stale_detection_run(run_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve summary of a stale detection run."""
    conn = get_connection()
    cursor = conn.cursor()
    row = cursor.execute("SELECT * FROM stale_detection_runs WHERE run_id = ?", (run_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_claims_for_run(run_id: str) -> List[Dict[str, Any]]:
    """Retrieve all claims belonging to a stale detection run."""
    conn = get_connection()
    cursor = conn.cursor()
    rows = cursor.execute("SELECT * FROM detection_claims WHERE run_id = ? ORDER BY created_at ASC", (run_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_evidence_for_claim(claim_id: str) -> List[Dict[str, Any]]:
    """Retrieve all documentation evidence items for a claim."""
    conn = get_connection()
    cursor = conn.cursor()
    rows = cursor.execute("SELECT * FROM claim_evidence WHERE claim_id = ? ORDER BY relevance_score DESC", (claim_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_correction_for_claim(claim_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve correction recommendation and suggested patch for a claim."""
    conn = get_connection()
    cursor = conn.cursor()
    row = cursor.execute("""
        SELECT claim_id, claim_text, technology, version, classification,
               confidence, reasoning, recommended_correction, suggested_patch, is_simulated
        FROM detection_claims WHERE claim_id = ?
    """, (claim_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def save_run_event(run_id: str, event_type: str, payload: Dict[str, Any]) -> int:
    """Persist an individual execution event to the database and return its row ID."""
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO run_events (run_id, event_type, payload_json, created_at)
        VALUES (?, ?, ?, ?)
    """, (run_id, event_type, json.dumps(payload), now_str))
    event_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return event_id

def get_run_events(run_id: str, after_id: int = 0) -> List[Dict[str, Any]]:
    """Retrieve all persisted events for a run, optionally filtering after a specific event ID."""
    conn = get_connection()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT id, run_id, event_type, payload_json, created_at
        FROM run_events
        WHERE run_id = ? AND id > ?
        ORDER BY id ASC
    """, (run_id, after_id)).fetchall()
    conn.close()

    events = []
    for r in rows:
        item = dict(r)
        try:
            item["payload"] = json.loads(item["payload_json"])
        except Exception:
            item["payload"] = {}
        events.append(item)
    return events

def save_execution_trace(run_id: str, trace_data: Dict[str, Any]):
    """Persist the complete execution summary trace into SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO execution_traces (run_id, trace_json, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET trace_json = excluded.trace_json
    """, (run_id, json.dumps(trace_data), now_str))
    conn.commit()
    conn.close()

def get_execution_trace(run_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve the persisted execution summary trace for a run."""
    conn = get_connection()
    cursor = conn.cursor()
    row = cursor.execute("SELECT trace_json FROM execution_traces WHERE run_id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row["trace_json"])
    except Exception:
        return None

def get_all_runs(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve recent runs from the database."""
    conn = get_connection()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT run_id, status, configuration, repo_path, prompt, token_budget,
               is_replay, metrics_json, created_at, completed_at
        FROM runs
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    results = []
    for r in rows:
        run_dict = dict(r)
        try:
            run_dict["metrics"] = json.loads(run_dict["metrics_json"] or "{}")
        except Exception:
            run_dict["metrics"] = {}
        results.append(run_dict)
    return results

def update_run_status(run_id: str, status: str, completed_at: Optional[str] = None):
    """Update execution status and optional completion timestamp for a run."""
    conn = get_connection()
    cursor = conn.cursor()
    if completed_at:
        cursor.execute("UPDATE runs SET status = ?, completed_at = ? WHERE run_id = ?", (status, completed_at, run_id))
    else:
        cursor.execute("UPDATE runs SET status = ? WHERE run_id = ?", (status, run_id))
    conn.commit()
    conn.close()

def seed_initial_demo_data():
    """Ensure pre-recorded canonical demo run trace is available for offline evaluation."""
    demo_file = Path(__file__).resolve().parent.parent / "traces" / "demo_pydantic_v2_migration.json"
    if not demo_file.exists():
        return

    conn = get_connection()
    cursor = conn.cursor()
    existing = cursor.execute("SELECT 1 FROM runs WHERE run_id = 'demo_trace_pydantic_v2_migration'").fetchone()
    if existing:
        conn.close()
        return

    try:
        with open(demo_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        run_id = data.get("run_id", "demo_trace_pydantic_v2_migration")
        task = data.get("task", "Migrate deprecated user.dict() to user.model_dump() in Pydantic v2")
        cfg = data.get("configuration", "leancode_tavily")
        status = data.get("status", "COMPLETED_VERIFIED")
        metrics = data.get("metrics", {})
        diff = data.get("diff", "")
        events = data.get("events", [])

        stale_claims = []
        for evt in events:
            if evt.get("type") == "stale_detection":
                claims = evt.get("data", {}).get("claims", [])
                stale_claims.extend(claims)

        now_str = datetime.now().isoformat()
        cursor.execute("""
            INSERT OR REPLACE INTO runs (
                run_id, status, configuration, repo_path, prompt, token_budget,
                is_replay, metrics_json, stale_detections_json, diff_text, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            status,
            cfg,
            "benchmark/tasks/task_pydantic_v2",
            task,
            15000,
            1,
            json.dumps(metrics),
            json.dumps(stale_claims),
            diff,
            now_str,
            now_str
        ))

        # Save run events
        for evt in events:
            cursor.execute("""
                INSERT INTO run_events (run_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?)
            """, (run_id, evt.get("type", "log"), json.dumps(evt), now_str))

        # Save execution trace
        cursor.execute("""
            INSERT OR REPLACE INTO execution_traces (run_id, trace_json, created_at)
            VALUES (?, ?, ?)
        """, (run_id, json.dumps(data), now_str))

        # Save model call
        cursor.execute("""
            INSERT INTO model_calls (
                run_id, call_id, model, provider, request_id,
                input_tokens, output_tokens, total_tokens, cached_tokens,
                latency_seconds, calculated_cost, is_simulated, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            "call_demo_01",
            "gpt-4o-mini",
            "bifrost (simulated)",
            "req_demo_pydantic_v2",
            195,
            42,
            237,
            0,
            0.52,
            0.000054,
            1,
            now_str
        ))
        conn.commit()
    except Exception as e:
        print(f"Failed to seed demo data: {e}")
    finally:
        conn.close()

    # Seed stale detection claims and evidence
    if stale_claims:
        try:
            save_stale_detection_run(
                run_id=run_id,
                task_description=task,
                status="completed",
                claims=[{
                    "claim_id": f"claim_demo_{idx}",
                    "claim_text": c.get("claim_text", ""),
                    "technology": c.get("technology", "pydantic"),
                    "version": "v2",
                    "priority": "high",
                    "classification": c.get("classification", "STALE"),
                    "confidence": c.get("confidence", 0.9),
                    "reasoning": c.get("evidence", ""),
                    "recommended_correction": c.get("recommended_correction", ""),
                    "suggested_patch": "return user.model_dump()",
                    "is_simulated": True
                } for idx, c in enumerate(stale_claims)],
                evidence_records=[{
                    "evidence_id": f"ev_demo_{idx}",
                    "claim_id": f"claim_demo_{idx}",
                    "url": c.get("source_url", "https://docs.pydantic.dev/latest/migration/"),
                    "domain": "docs.pydantic.dev",
                    "title": "Pydantic Migration Guide",
                    "excerpt": c.get("evidence", ""),
                    "relevance_score": 0.95,
                    "is_simulated": True
                } for idx, c in enumerate(stale_claims)],
                searches_executed=1,
                search_budget=5,
                is_simulated=True
            )
        except Exception:
            pass

init_db()
seed_initial_demo_data()
