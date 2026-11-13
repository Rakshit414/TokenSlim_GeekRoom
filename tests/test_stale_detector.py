"""Comprehensive unit and integration tests for TokenSlim Stale-Answer Detection Engine.
Verifies all 15 acceptance criteria: CURRENT, STALE, UNCERTAIN classifications,
Tavily mocking, budget limits, deduplication, persistence, and REST endpoints.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from agent.docs_check import TavilyDocsClient, TavilyEvidence, TavilyVerificationResult
from agent.stale_detector import StaleAnswerDetector, Claim, ClaimEvidence
from server.database import (
    init_db, get_connection, get_stale_detection_run,
    get_claims_for_run, get_evidence_for_claim, get_correction_for_claim
)
from server.app import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_database():
    """Ensure clean database for test execution."""
    init_db()

def create_mock_tavily_client(evidence_items, is_simulated=False, raises_exc=None):
    """Helper to generate deterministic mock TavilyDocsClient."""
    mock_client = MagicMock(spec=TavilyDocsClient)
    mock_client.is_configured = True

    if raises_exc:
        mock_client.search_docs.side_effect = raises_exc
    else:
        res = TavilyVerificationResult(
            query="test",
            evidence_items=evidence_items,
            is_live=not is_simulated,
            is_simulated=is_simulated,
            search_duration_seconds=0.15
        )
        mock_client.search_docs.return_value = res

    return mock_client

def test_current_api_claim():
    """Verify that claims supported by modern documentation are classified as CURRENT."""
    evidence = [
        TavilyEvidence(
            query="pydantic model_validate",
            source_title="Pydantic V2 Documentation - Model Methods",
            source_url="https://docs.pydantic.dev/latest/concepts/models/",
            snippet="BaseModel.model_validate(obj) is the current recommended approach in Pydantic V2 to validate data.",
            score=0.92,
            date_retrieved="2026-11-13 10:00:00 UTC",
            is_simulated=False
        )
    ]
    mock_tavily = create_mock_tavily_client(evidence)
    detector = StaleAnswerDetector(tavily_client=mock_tavily)

    claim = Claim(
        claim_id="c_curr_1",
        claim_text="Use BaseModel.model_validate(data) for parsing inputs in Pydantic v2",
        technology="pydantic",
        version="v2"
    )

    verified, ev_list, spent = detector.verify_claim(claim, searches_remaining=3)

    assert verified.classification == "CURRENT"
    assert verified.confidence >= 0.70
    assert "supports" in verified.reasoning.lower()
    assert verified.recommended_correction is None
    assert len(ev_list) == 1
    assert spent == 1

def test_deprecated_api_claim():
    """Verify that deprecated method claims are classified as STALE with recommended alternatives."""
    evidence = [
        TavilyEvidence(
            query="pydantic model dict",
            source_title="Pydantic V2 Migration Guide - Deprecations",
            source_url="https://docs.pydantic.dev/latest/migration/#model-methods",
            snippet="The .dict() method is deprecated in Pydantic V2 and superseded by .model_dump(). It will be removed in future releases.",
            score=0.95,
            date_retrieved="2026-11-13 10:00:00 UTC",
            is_simulated=False
        )
    ]
    mock_tavily = create_mock_tavily_client(evidence)
    detector = StaleAnswerDetector(tavily_client=mock_tavily)

    claim = Claim(
        claim_id="c_stale_1",
        claim_text="Call user.dict() to serialize Pydantic model",
        technology="pydantic",
        version="v2"
    )

    verified, ev_list, spent = detector.verify_claim(claim, searches_remaining=3)

    assert verified.classification == "STALE"
    assert verified.confidence >= 0.80
    assert "deprecated" in verified.reasoning.lower()
    assert verified.recommended_correction is not None
    assert "model_dump" in verified.recommended_correction
    assert verified.suggested_patch is not None
    assert "- return model.dict()" in verified.suggested_patch

def test_removed_endpoint():
    """Verify that claims about removed API endpoints are classified as STALE."""
    evidence = [
        TavilyEvidence(
            query="openai completion create",
            source_title="OpenAI API v1.0 Migration Guide",
            source_url="https://platform.openai.com/docs/guides/text-generation",
            snippet="openai.Completion.create endpoint is deprecated and no longer supported. Use ChatCompletions API instead.",
            score=0.91,
            date_retrieved="2026-11-13 10:00:00 UTC",
            is_simulated=False
        )
    ]
    mock_tavily = create_mock_tavily_client(evidence)
    detector = StaleAnswerDetector(tavily_client=mock_tavily)

    claim = Claim(
        claim_id="c_removed_1",
        claim_text="Legacy openai.Completion.create(model='text-davinci-003')",
        technology="openai"
    )

    verified, ev_list, _ = detector.verify_claim(claim, searches_remaining=2)

    assert verified.classification == "STALE"
    assert "deprecated" in verified.reasoning.lower() or "superseded" in verified.reasoning.lower()
    assert verified.recommended_correction is not None

def test_outdated_sdk_method():
    """Verify that outdated SDK invocation patterns in code snippets are extracted and marked STALE."""
    code_files = {
        "services/llm.py": "def run():\n    resp = openai.ChatCompletion.create(model='gpt-4')\n    return resp\n"
    }
    evidence = [
        TavilyEvidence(
            query="openai ChatCompletion create",
            source_title="OpenAI Python v1.0.0 Migration Guide",
            source_url="https://github.com/openai/openai-python/blob/main/MIGRATION.md",
            snippet="openai.ChatCompletion.create() was removed in v1.0+. Use client = OpenAI(); client.chat.completions.create().",
            score=0.96,
            date_retrieved="2026-11-13 10:00:00 UTC",
            is_simulated=False
        )
    ]
    mock_tavily = create_mock_tavily_client(evidence)
    detector = StaleAnswerDetector(tavily_client=mock_tavily)

    run = detector.run_detection(
        task="Audit OpenAI SDK calls in codebase",
        code_snippets=code_files,
        persist=False
    )

    assert len(run.claims) >= 1
    stale_claims = run.stale_claims
    assert len(stale_claims) == 1
    assert stale_claims[0].file_path == "services/llm.py"
    assert "llm.py" in stale_claims[0].claim_text
    assert stale_claims[0].classification == "STALE"
    assert "OpenAI()" in (stale_claims[0].recommended_correction or "")

def test_version_mismatch():
    """Verify version-specific deprecations (e.g. datetime.utcnow in Python 3.12+)."""
    evidence = [
        TavilyEvidence(
            query="python datetime utcnow deprecated",
            source_title="Python 3.12 Release Notes - Deprecations",
            source_url="https://docs.python.org/3/whatsnew/3.12.html",
            snippet="datetime.datetime.utcnow() is deprecated since Python 3.12. Use datetime.datetime.now(timezone.utc) instead.",
            score=0.94,
            date_retrieved="2026-11-13 10:00:00 UTC",
            is_simulated=False
        )
    ]
    mock_tavily = create_mock_tavily_client(evidence)
    detector = StaleAnswerDetector(tavily_client=mock_tavily)

    claim = Claim(
        claim_id="c_dt_1",
        claim_text="datetime.utcnow() method usage in Python",
        technology="python",
        version="3.12"
    )

    verified, _, _ = detector.verify_claim(claim, searches_remaining=2)

    assert verified.classification == "STALE"
    assert "datetime.now(timezone.utc)" in (verified.recommended_correction or "")

def test_insufficient_evidence():
    """CRITICAL: Empty or zero evidence items must result in UNCERTAIN, never STALE."""
    # Tavily returns no results
    mock_tavily = create_mock_tavily_client([])
    detector = StaleAnswerDetector(tavily_client=mock_tavily)

    claim = Claim(
        claim_id="c_empty_1",
        claim_text="Hypothetical unknown function obscure_tool.process()",
        technology="unknown"
    )

    verified, ev_list, spent = detector.verify_claim(claim, searches_remaining=2)

    assert verified.classification == "UNCERTAIN"
    assert verified.confidence == 0.0
    assert "no documentation evidence" in verified.reasoning.lower()
    assert verified.recommended_correction is None
    assert len(ev_list) == 0

def test_conflicting_documentation():
    """Verify that ambiguous or conflicting documentation results in UNCERTAIN."""
    evidence = [
        TavilyEvidence(
            query="mixed tool",
            source_title="Forum Discussion",
            source_url="https://forum.example.com/topic/1",
            snippet="Some users report issues while others say it works fine.",
            score=0.45,
            date_retrieved="2026-11-13 10:00:00 UTC",
            is_simulated=False
        )
    ]
    mock_tavily = create_mock_tavily_client(evidence)
    detector = StaleAnswerDetector(tavily_client=mock_tavily)

    claim = Claim(
        claim_id="c_conflict_1",
        claim_text="Ambiguous configuration setting",
        technology="general"
    )

    verified, _, _ = detector.verify_claim(claim, searches_remaining=2)

    assert verified.classification == "UNCERTAIN"
    assert "conclusive" in verified.reasoning.lower() or "ambiguous" in verified.reasoning.lower()

def test_tavily_timeout():
    """Verify that external search timeouts are handled gracefully without aborting."""
    mock_tavily = create_mock_tavily_client([], raises_exc=TimeoutError("Tavily gateway request timed out"))
    detector = StaleAnswerDetector(tavily_client=mock_tavily)

    claim = Claim(
        claim_id="c_timeout_1",
        claim_text="Verify some API method",
        technology="python"
    )

    verified, ev_list, spent = detector.verify_claim(claim, searches_remaining=2)

    assert verified.classification == "UNCERTAIN"
    assert verified.confidence == 0.0
    assert "timed out" in verified.reasoning.lower()
    assert len(ev_list) == 0

def test_missing_tavily_credentials():
    """Verify fallback simulation when Tavily credentials are missing."""
    with patch.dict("os.environ", {"TAVILY_API_KEY": ""}, clear=False):
        tavily = TavilyDocsClient(api_key="")
        detector = StaleAnswerDetector(tavily_client=tavily)

        claim = Claim(
            claim_id="c_mock_1",
            claim_text="Verify method when offline",
            technology="python"
        )

        verified, ev_list, _ = detector.verify_claim(claim, searches_remaining=2)

        assert verified.is_simulated is True
        assert len(ev_list) == 1
        assert ev_list[0].is_simulated is True
        assert "[SIMULATED - OFFLINE]" in ev_list[0].title

def test_search_budget_enforcement():
    """Verify that search budget is strictly enforced and halts subsequent search calls."""
    evidence = [
        TavilyEvidence(
            query="test",
            source_title="Reference",
            source_url="https://docs.example.com",
            snippet="Current active API reference",
            score=0.8,
            date_retrieved="2026-11-13 10:00:00 UTC",
            is_simulated=False
        )
    ]
    mock_tavily = create_mock_tavily_client(evidence)
    detector = StaleAnswerDetector(tavily_client=mock_tavily, search_budget=2)

    explicit_claims = [
        {"claim_text": f"Claim {i}", "technology": f"tech_{i}"} for i in range(1, 5)
    ]

    run = detector.run_detection(
        task="Test budget enforcement",
        explicit_claims=explicit_claims,
        max_searches=2,
        persist=False
    )

    # Searches executed must not exceed budget of 2
    assert run.searches_executed == 2
    assert mock_tavily.search_docs.call_count == 2

    # First two were verified; 3rd and 4th were marked UNCERTAIN due to budget
    assert run.claims[0].classification in ("CURRENT", "STALE")
    assert run.claims[1].classification in ("CURRENT", "STALE")
    assert run.claims[2].classification == "UNCERTAIN"
    assert "budget exhausted" in run.claims[2].reasoning.lower()
    assert run.claims[3].classification == "UNCERTAIN"
    assert "budget exhausted" in run.claims[3].reasoning.lower()

def test_duplicate_claim_handling():
    """Verify that identical claims in the same run reuse cached search results."""
    evidence = [
        TavilyEvidence(
            query="query",
            source_title="Doc",
            source_url="https://docs.pydantic.dev",
            snippet="model.dict() is deprecated",
            score=0.9,
            date_retrieved="2026-11-13 10:00:00 UTC",
            is_simulated=False
        )
    ]
    mock_tavily = create_mock_tavily_client(evidence)
    detector = StaleAnswerDetector(tavily_client=mock_tavily, search_budget=5)

    # Two identical claims
    claims = [
        {"claim_text": "BaseModel.dict()", "technology": "pydantic"},
        {"claim_text": "BaseModel.dict()", "technology": "pydantic"}
    ]

    run = detector.run_detection(
        task="Deduplication test",
        explicit_claims=claims,
        persist=False
    )

    assert len(run.claims) == 2
    # Only 1 search should have been executed via Tavily API
    assert mock_tavily.search_docs.call_count == 1
    assert run.searches_executed == 1
    assert run.claims[0].classification == "STALE"
    assert run.claims[1].classification == "STALE"

def test_evidence_persistence():
    """Verify SQLite persistence for stale detection runs, claims, and evidence."""
    evidence = [
        TavilyEvidence(
            query="test",
            source_title="Pydantic Reference",
            source_url="https://docs.pydantic.dev/2.0/migration/",
            snippet="Deprecation notice for parse_obj in v2",
            score=0.88,
            date_retrieved="2026-11-13 10:00:00 UTC",
            is_simulated=False
        )
    ]
    mock_tavily = create_mock_tavily_client(evidence)
    detector = StaleAnswerDetector(tavily_client=mock_tavily)

    run = detector.run_detection(
        task="Persist test run",
        explicit_claims=[{"claim_text": "parse_obj usage", "technology": "pydantic"}],
        persist=True
    )

    persisted_run = get_stale_detection_run(run.run_id)
    assert persisted_run is not None
    assert persisted_run["run_id"] == run.run_id
    assert persisted_run["total_claims"] == 1

    claims = get_claims_for_run(run.run_id)
    assert len(claims) == 1
    claim_id = claims[0]["claim_id"]
    assert claims[0]["technology"] == "pydantic"

    ev_records = get_evidence_for_claim(claim_id)
    assert len(ev_records) == 1
    assert ev_records[0]["url"] == "https://docs.pydantic.dev/2.0/migration/"
    assert ev_records[0]["relevance_score"] == pytest.approx(0.88, rel=1e-3)

def test_source_url_preservation():
    """Verify that source URLs and domains are accurately preserved without distortion."""
    target_url = "https://docs.python.org/3/library/importlib.html#module-importlib.resources"
    evidence = [
        TavilyEvidence(
            query="python importlib",
            source_title="Python standard library documentation",
            source_url=target_url,
            snippet="importlib.resources provides access to resources within Python packages.",
            score=0.91,
            date_retrieved="2026-11-13 10:00:00 UTC",
            is_simulated=False
        )
    ]
    mock_tavily = create_mock_tavily_client(evidence)
    detector = StaleAnswerDetector(tavily_client=mock_tavily)

    claim = Claim(
        claim_id="c_url_1",
        claim_text="Use importlib.resources",
        technology="python"
    )

    _, ev_list, _ = detector.verify_claim(claim, searches_remaining=2)

    assert len(ev_list) == 1
    assert ev_list[0].url == target_url
    assert ev_list[0].domain == "docs.python.org"

def test_simulated_vs_live_evidence_labelling():
    """Verify that simulated and live evidence items are strictly distinguished."""
    live_ev = TavilyEvidence(
        query="live", source_title="Live", source_url="https://live.org",
        snippet="live doc", score=0.9, date_retrieved="2026-11-13 10:00:00 UTC",
        is_simulated=False
    )
    sim_ev = TavilyEvidence(
        query="sim", source_title="[SIMULATED - OFFLINE]", source_url="https://mock.invalid",
        snippet="mock doc", score=0.0, date_retrieved="2026-11-13 10:00:00 UTC",
        is_simulated=True
    )

    mock_live = create_mock_tavily_client([live_ev], is_simulated=False)
    detector_live = StaleAnswerDetector(tavily_client=mock_live)
    claim1, _, _ = detector_live.verify_claim(Claim(claim_id="1", claim_text="test1", technology="python"), 2)
    assert claim1.is_simulated is False

    mock_sim = create_mock_tavily_client([sim_ev], is_simulated=True)
    detector_sim = StaleAnswerDetector(tavily_client=mock_sim)
    claim2, _, _ = detector_sim.verify_claim(Claim(claim_id="2", claim_text="test2", technology="python"), 2)
    assert claim2.is_simulated is True

def test_api_response_structure():
    """Verify FastAPI REST endpoints for starting runs and retrieving claims/evidence."""
    # Run a detection via API
    resp = client.post("/api/stale-detection/runs", json={
        "task": "API endpoint verification run",
        "claims": [
            {"claim_text": "pydantic model.dict() method", "technology": "pydantic"}
        ],
        "max_searches": 3
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert data["total_claims"] == 1
    run_id = data["run_id"]
    claim_id = data["claims"][0]["claim_id"]

    # Retrieve run
    get_run_resp = client.get(f"/api/stale-detection/runs/{run_id}")
    assert get_run_resp.status_code == 200
    assert get_run_resp.json()["run"]["run_id"] == run_id

    # Retrieve claims
    get_claims_resp = client.get(f"/api/stale-detection/runs/{run_id}/claims")
    assert get_claims_resp.status_code == 200
    assert len(get_claims_resp.json()["claims"]) == 1

    # Retrieve evidence for claim
    get_ev_resp = client.get(f"/api/stale-detection/claims/{claim_id}/evidence")
    assert get_ev_resp.status_code == 200
    assert "evidence" in get_ev_resp.json()

    # Retrieve correction recommendation
    get_corr_resp = client.get(f"/api/stale-detection/claims/{claim_id}/correction")
    assert get_corr_resp.status_code == 200
    assert get_corr_resp.json()["claim_id"] == claim_id
