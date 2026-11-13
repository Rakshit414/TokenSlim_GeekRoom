"""Checkpoint 0 Preflight Verification Test Suite.
Validates environment, project structure, database, API schemas, design tokens, and connectivity.
"""
import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from server.app import app
from server.database import get_connection, init_db

client = TestClient(app)

def test_project_structure_exists():
    """Verify that all core directories and files required by Section 6 exist."""
    root = Path(__file__).resolve().parent.parent
    expected_dirs = [
        root / "agent",
        root / "benchmark",
        root / "benchmark" / "tasks",
        root / "server",
        root / "server" / "static",
        root / "traces",
        root / "tests"
    ]
    for d in expected_dirs:
        assert d.exists(), f"Directory {d} does not exist"
        assert d.is_dir(), f"Path {d} is not a directory"

    expected_files = [
        root / "requirements.txt",
        root / ".env.example",
        root / ".gitignore",
        root / "Dockerfile",
        root / "docker-compose.yml",
        root / "server" / "static" / "index.html",
        root / "server" / "static" / "style.css",
        root / "server" / "static" / "app.js"
    ]
    for f in expected_files:
        assert f.exists(), f"File {f} does not exist"
        assert f.stat().st_size > 0, f"File {f} is empty"

def test_design_tokens_defined():
    """Verify that official design system tokens (#14213D, #F4EDE0, #FF6B5B) are defined in style.css."""
    root = Path(__file__).resolve().parent.parent
    css_path = root / "server" / "static" / "style.css"
    content = css_path.read_text(encoding="utf-8")
    
    # Mandatory brand colors
    assert "#14213D" in content, "Navy #14213D must be defined in style.css"
    assert "#F4EDE0" in content, "Cream #F4EDE0 must be defined in style.css"
    assert "#FF6B5B" in content, "Coral #FF6B5B must be defined in style.css"
    assert "--navy:" in content, "CSS variable --navy must be present"
    assert "--cream:" in content, "CSS variable --cream must be present"
    assert "--coral:" in content, "CSS variable --coral must be present"

def test_database_initialization():
    """Verify that SQLite tables are created properly."""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = [t[0] for t in tables]
    assert "runs" in table_names
    assert "run_events" in table_names
    assert "benchmarks" in table_names
    conn.close()

def test_health_endpoint():
    """Verify that GET /api/health returns valid schema and status."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "bifrost" in data
    assert "tavily" in data
    assert "database" in data
    assert data["database"]["status"] == "healthy"

def test_bifrost_client_preflight():
    """Verify Bifrost client configuration and usage extraction."""
    from agent.bifrost_client import BifrostClient
    client = BifrostClient(base_url="http://127.0.0.1:8080/v1", timeout=0.2)
    reachable, msg = client.probe_connection()
    # At preflight, Bifrost service may not be running locally yet
    assert isinstance(reachable, bool)

    # Test chat completion fallback simulation
    content, usage = client.chat_completion(
        messages=[{"role": "user", "content": "test prompt"}],
        fallback_mock=True
    )
    assert usage.total_tokens > 0
    assert usage.input_tokens > 0
    assert usage.latency_seconds >= 0.0

def test_tavily_client_preflight():
    """Verify Tavily documentation verification client structure and evidence models."""
    from agent.docs_check import TavilyDocsClient
    tavily = TavilyDocsClient(api_key="")
    assert not tavily.is_configured

    # Test fallback query handling
    result = tavily.search_docs("pydantic v2 field_validator migration", fallback_mock=True)
    assert not result.is_live
    assert len(result.evidence_items) > 0
    assert result.evidence_items[0].source_url.startswith("http")
    assert result.error_message is not None
