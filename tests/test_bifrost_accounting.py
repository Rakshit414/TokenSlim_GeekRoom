"""Test suite for Bifrost gateway integration, token accounting, and cost tracking (Checkpoint 3).
Validates usage parsing, cached tokens, cost calculations, missing fields, timeouts, auth errors,
request ID tracking, and separation of provider vs estimated vs mock tokens.
"""
import pytest
from unittest.mock import MagicMock
from openai import APITimeoutError, AuthenticationError, APIConnectionError
from fastapi.testclient import TestClient

from agent.bifrost_client import BifrostClient, BifrostUsage
from agent.metrics import (
    ModelPricing,
    MODEL_PRICING_CATALOG,
    calculate_call_cost,
    ModelCallRecord,
    RunMetricsLedger
)
from server.app import app
from server.database import init_db, get_connection

client = TestClient(app)

def test_successful_gateway_response_parsing():
    """Verify that provider usage and request ID are parsed accurately from a Bifrost response."""
    bifrost = BifrostClient(base_url="http://localhost:8080/v1")

    # Mock response object matching OpenAI API schema returned by Bifrost
    mock_resp = MagicMock()
    mock_resp.id = "chatcmpl-bifrost-98765"
    mock_resp.model = "gpt-4o-mini"
    mock_resp.choices = [MagicMock(message=MagicMock(content="def fix(): return True"))]
    mock_resp.usage.prompt_tokens = 320
    mock_resp.usage.completion_tokens = 85
    mock_resp.usage.total_tokens = 405
    mock_resp.usage.prompt_tokens_details = None

    bifrost._client.chat.completions.create = MagicMock(return_value=mock_resp)

    content, usage = bifrost.chat_completion(
        messages=[{"role": "user", "content": "fix bug"}],
        model="gpt-4o-mini",
        fallback_mock=False
    )

    assert usage.is_simulated is False
    assert usage.provider_reported_input_tokens == 320
    assert usage.provider_reported_output_tokens == 85
    assert usage.provider_reported_total_tokens == 405
    assert usage.input_tokens == 320
    assert usage.output_tokens == 85
    assert usage.total_tokens == 405
    assert usage.request_id == "chatcmpl-bifrost-98765"
    assert usage.model == "gpt-4o-mini"
    assert usage.estimated_cost is not None
    assert usage.estimated_cost > 0.0

def test_missing_usage_fields():
    """Verify that missing usage metadata is preserved as unavailable without fabricating numbers."""
    bifrost = BifrostClient(base_url="http://localhost:8080/v1")

    mock_resp = MagicMock()
    mock_resp.id = "req-no-usage"
    mock_resp.model = "gpt-4o-mini"
    mock_resp.choices = [MagicMock(message=MagicMock(content="result"))]
    mock_resp.usage = None  # Provider omitted usage

    bifrost._client.chat.completions.create = MagicMock(return_value=mock_resp)

    content, usage = bifrost.chat_completion(
        messages=[{"role": "user", "content": "test"}],
        model="gpt-4o-mini",
        fallback_mock=False
    )

    assert usage.is_simulated is False
    assert usage.provider_reported_input_tokens == 0
    assert usage.estimated_cost is None
    assert "unavailable" in (usage.cost_calculation_note or "").lower()

def test_cached_token_handling():
    """Verify that cached prompt tokens are parsed and billed at reduced cached rate."""
    bifrost = BifrostClient(base_url="http://localhost:8080/v1")

    mock_resp = MagicMock()
    mock_resp.id = "req-cache"
    mock_resp.model = "gpt-4o-mini"
    mock_resp.choices = [MagicMock(message=MagicMock(content="cached response"))]
    mock_resp.usage.prompt_tokens = 1000
    mock_resp.usage.completion_tokens = 100
    mock_resp.usage.total_tokens = 1100
    mock_resp.usage.prompt_tokens_details = MagicMock(cached_tokens=800)

    bifrost._client.chat.completions.create = MagicMock(return_value=mock_resp)

    content, usage = bifrost.chat_completion(
        messages=[{"role": "user", "content": "prompt"}],
        model="gpt-4o-mini",
        fallback_mock=False
    )

    assert usage.cached_tokens == 800
    # gpt-4o-mini: uncached 200 * $0.15/1M ($0.000030) + cached 800 * $0.075/1M ($0.000060) + output 100 * $0.60/1M ($0.000060) = $0.000150
    assert usage.estimated_cost == pytest.approx(0.000150, rel=1e-3)

def test_unknown_model_pricing():
    """Verify that unknown models return None for cost rather than fabricating numbers."""
    cost, note = calculate_call_cost("unknown-provider/obscure-llm-v1", input_tokens=1000, output_tokens=500)
    assert cost is None
    assert "no rate entry in pricing catalog" in note

def test_cost_calculation_accuracy():
    """Verify mathematical accuracy of cost calculation against known rates."""
    # gpt-4o: 1000 input ($0.00250) + 500 output ($0.00500) = $0.00750
    cost_4o, _ = calculate_call_cost("gpt-4o", input_tokens=1000, output_tokens=500)
    assert cost_4o == pytest.approx(0.0075, rel=1e-4)

    # claude-3-5-sonnet: 2000 input ($0.006) + 1000 output ($0.015) = $0.021
    cost_sonnet, _ = calculate_call_cost("claude-3-5-sonnet-20241022", input_tokens=2000, output_tokens=1000)
    assert cost_sonnet == pytest.approx(0.021, rel=1e-4)

def test_gateway_timeout_handling():
    """Verify graceful handling when gateway times out."""
    bifrost = BifrostClient(base_url="http://localhost:8080/v1")
    req = MagicMock()
    bifrost._client.chat.completions.create = MagicMock(side_effect=APITimeoutError(request=req))

    with pytest.raises(APITimeoutError):
        bifrost.chat_completion(
            messages=[{"role": "user", "content": "test"}],
            fallback_mock=False
        )

def test_authentication_failure_handling():
    """Verify that authentication errors are propagated without leaking credentials."""
    bifrost = BifrostClient(base_url="http://localhost:8080/v1")
    resp = MagicMock(status_code=401, headers={})
    body = {"error": {"message": "Invalid Bifrost API Key"}}
    bifrost._client.chat.completions.create = MagicMock(
        side_effect=AuthenticationError(message="Invalid Bifrost API Key", response=resp, body=body)
    )

    with pytest.raises(AuthenticationError) as exc_info:
        bifrost.chat_completion(
            messages=[{"role": "user", "content": "test"}],
            fallback_mock=False
        )
    assert "Invalid Bifrost API Key" in str(exc_info.value)

def test_multiple_model_calls_in_ledger():
    """Verify that RunMetricsLedger accumulates multiple calls accurately."""
    ledger = RunMetricsLedger(run_id="run_multi_test")

    call1 = ModelCallRecord(
        call_id="c1", run_id="run_multi_test", model="gpt-4o-mini", provider="bifrost",
        request_id="req-1", input_tokens=200, output_tokens=50, total_tokens=250,
        cached_input_tokens=0, latency_seconds=0.5, calculated_cost=0.000060,
        is_simulated=False, timestamp="2026-03-01 10:00:00"
    )
    call2 = ModelCallRecord(
        call_id="c2", run_id="run_multi_test", model="gpt-4o-mini", provider="bifrost",
        request_id="req-2", input_tokens=300, output_tokens=100, total_tokens=400,
        cached_input_tokens=100, latency_seconds=0.7, calculated_cost=0.0000975,
        is_simulated=False, timestamp="2026-03-01 10:00:05"
    )

    ledger.add_call(call1)
    ledger.add_call(call2)

    assert ledger.provider_input_tokens == 500
    assert ledger.provider_output_tokens == 150
    assert ledger.provider_total_tokens == 650
    assert ledger.provider_cached_tokens == 100
    assert ledger.simulated_total_tokens == 0
    assert ledger.total_cost == pytest.approx(0.0001575, rel=1e-4)
    assert ledger.average_latency_seconds == 0.6

def test_separation_of_estimated_and_provider_tokens():
    """Verify that local AST context token estimates are strictly segregated from provider totals."""
    ledger = RunMetricsLedger(run_id="run_segregate", locally_estimated_context_tokens=1250)

    real_call = ModelCallRecord(
        call_id="c1", run_id="run_segregate", model="gpt-4o-mini", provider="bifrost",
        input_tokens=350, output_tokens=80, total_tokens=430,
        is_simulated=False, timestamp="2026-03-01"
    )
    ledger.add_call(real_call)

    # Provider total must NEVER include estimated context tokens
    assert ledger.provider_total_tokens == 430
    assert ledger.locally_estimated_context_tokens == 1250
    summary = ledger.to_summary_dict()
    assert summary["provider_reported_usage"]["total_tokens"] == 430
    assert summary["locally_estimated_context_tokens"] == 1250

def test_separation_of_real_and_mock_usage():
    """Verify that mock/simulated calls are never added to provider-reported totals."""
    ledger = RunMetricsLedger(run_id="run_mock_sep")

    real_call = ModelCallRecord(
        call_id="real1", run_id="run_mock_sep", model="gpt-4o-mini", provider="bifrost",
        input_tokens=500, output_tokens=100, total_tokens=600,
        is_simulated=False, timestamp="2026-03-01"
    )
    mock_call = ModelCallRecord(
        call_id="mock1", run_id="run_mock_sep", model="mock-agent", provider="mock-adapter",
        input_tokens=150, output_tokens=50, total_tokens=200,
        is_simulated=True, timestamp="2026-03-01"
    )

    ledger.add_call(real_call)
    ledger.add_call(mock_call)

    # Real provider total must ONLY be 600
    assert ledger.provider_total_tokens == 600
    # Mock total must ONLY be 200
    assert ledger.simulated_total_tokens == 200

    summary = ledger.to_summary_dict()
    assert summary["real_provider_calls_count"] == 1
    assert summary["simulated_calls_count"] == 1
    assert summary["is_purely_simulated"] is False

def test_gateway_accounting_cross_check_logic():
    """Verify cross-check reconciliation between gateway response and recorded usage."""
    mock_resp = MagicMock()
    mock_resp.usage.prompt_tokens = 400
    mock_resp.usage.completion_tokens = 100
    mock_resp.usage.total_tokens = 500

    matching_usage = BifrostUsage(
        provider_reported_input_tokens=400,
        provider_reported_output_tokens=100,
        provider_reported_total_tokens=500
    )
    mismatch_usage = BifrostUsage(
        provider_reported_input_tokens=350,
        provider_reported_output_tokens=100,
        provider_reported_total_tokens=450
    )

    match_check = BifrostClient.cross_check_usage(mock_resp, matching_usage)
    assert match_check["verified"] is True
    assert match_check["diff_tokens"] == 0

    mismatch_check = BifrostClient.cross_check_usage(mock_resp, mismatch_usage)
    assert mismatch_check["verified"] is False
    assert mismatch_check["diff_tokens"] == -50

def test_api_metrics_endpoint():
    """Verify that GET /api/runs/{run_id}/metrics returns granular accounting data."""
    init_db()
    run_id = "test_metrics_api_run"

    # Clean up and insert test run and model call
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM model_calls WHERE run_id = ?", (run_id,))
    cursor.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
    cursor.execute("""
        INSERT INTO runs (run_id, status, configuration, repo_path, prompt, metrics_json, created_at)
        VALUES (?, 'completed', 'leancode_tavily', 'test/repo', 'fix', '{"total_tokens": 500}', datetime('now'))
    """, (run_id,))
    cursor.execute("""
        INSERT INTO model_calls (
            run_id, call_id, model, provider, request_id, input_tokens, output_tokens,
            total_tokens, cached_tokens, latency_seconds, calculated_cost, is_simulated, created_at
        ) VALUES (?, 'call_1', 'gpt-4o-mini', 'bifrost', 'bf-req-99', 400, 100, 500, 0, 0.45, 0.00012, 0, datetime('now'))
    """, (run_id,))
    conn.commit()
    conn.close()

    resp = client.get(f"/api/runs/{run_id}/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == run_id
    assert data["status"] == "completed"
    assert data["total_calls"] == 1
    assert data["model_calls"][0]["model"] == "gpt-4o-mini"
    assert data["model_calls"][0]["request_id"] == "bf-req-99"
    assert data["model_calls"][0]["calculated_cost"] == 0.00012
