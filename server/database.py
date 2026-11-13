"""SQLite database storage for TokenSlim execution runs, events, and benchmarks."""
import sqlite3
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

DB_PATH = Path(__file__).resolve().parent.parent / "tokenslim.db"

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
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

init_db()
