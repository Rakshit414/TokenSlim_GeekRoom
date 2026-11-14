"""Unit and integration tests for TokenSlim Checkpoint 5:
Benchmark Tasks, Stale-Answer Repair Integration, and 3-Way Comparative Evaluation.
"""
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from agent.loop import AutonomousCodingLoop, ExecutionSummary
from agent.stale_detector import StaleAnswerDetector, Claim, ClaimEvidence
from agent.bifrost_client import BifrostClient
from agent.docs_check import TavilyDocsClient, TavilyEvidence, TavilyVerificationResult
from benchmark.runner import BenchmarkRunner, TaskBenchmarkRunResult, TASKS_DIR

def copy_task_files(src_dir: Path, dst_dir: Path):
    """Safely copy task source files avoiding __pycache__ and metadata."""
    for item in src_dir.iterdir():
        if item.name in ("task.json", "__pycache__"):
            continue
        if item.is_file():
            shutil.copy2(item, dst_dir / item.name)
        elif item.is_dir():
            shutil.copytree(item, dst_dir / item.name, ignore=shutil.ignore_patterns("__pycache__"))

@pytest.fixture
def temp_task_dir():
    """Create a temporary workspace copying task_03 for isolated testing."""
    src = TASKS_DIR / "task_03_pydantic_v2_dict_deprecation"
    temp_dir = tempfile.mkdtemp(prefix="test_integration_")
    copy_task_files(src, Path(temp_dir))
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)

def test_stale_detection_integrated_into_coding_loop(temp_task_dir):
    """Verify that stale-answer detection runs and populates guidance in leancode_tavily."""
    # Mock Tavily docs client returning STALE deprecation evidence
    mock_tavily = MagicMock(spec=TavilyDocsClient)
    mock_tavily.is_configured = True
    mock_tavily.search_docs.return_value = TavilyVerificationResult(
        query="pydantic dict",
        evidence_items=[
            TavilyEvidence(
                query="pydantic dict",
                source_title="Pydantic V2 Migration Guide",
                source_url="https://docs.pydantic.dev/migration/",
                snippet="dict() is deprecated in v2, use model_dump()",
                score=0.95,
                date_retrieved="2026-11-14 10:00:00 UTC",
                is_simulated=False
            )
        ],
        is_live=True,
        is_simulated=False
    )
    detector = StaleAnswerDetector(tavily_client=mock_tavily)

    loop = AutonomousCodingLoop(
        workspace_dir=temp_task_dir,
        task_directive="Migrate user serializer from deprecated dict() to model_dump()",
        configuration="leancode_tavily",
        stale_detector=detector,
        mock_patch_generator=lambda it, fail, err: """FILE: models.py
<<<<<<< SEARCH
def serialize_user(user: UserProfile) -> dict:
    # Stale/deprecated API usage in Pydantic v2
    return user.dict()
=======
def serialize_user(user: UserProfile) -> dict:
    return user.model_dump()
>>>>>>> REPLACE"""
    )

    summary = loop.run()
    assert summary.status == "COMPLETED_VERIFIED"
    assert summary.tests_passed is True
    assert summary.configuration == "leancode_tavily"
    assert len(summary.stale_detections) >= 1
    assert any(d["classification"] == "STALE" for d in summary.stale_detections)
    assert summary.tavily_searches >= 1

def test_current_claims_left_unchanged():
    """Verify that CURRENT claims do not trigger unnecessary code changes."""
    src = TASKS_DIR / "task_08_current_api_preserved"
    temp_dir = tempfile.mkdtemp(prefix="test_current_")
    try:
        copy_task_files(src, Path(temp_dir))

        # Mock Tavily returning CURRENT active documentation
        mock_tavily = MagicMock(spec=TavilyDocsClient)
        mock_tavily.is_configured = True
        mock_tavily.search_docs.return_value = TavilyVerificationResult(
            query="pydantic Field",
            evidence_items=[
                TavilyEvidence(
                    query="pydantic Field",
                    source_title="Pydantic Concepts - Fields",
                    source_url="https://docs.pydantic.dev/concepts/fields/",
                    snippet="Field is current and active in Pydantic V2.",
                    score=0.90,
                    date_retrieved="2026-11-14 10:00:00 UTC",
                    is_simulated=False
                )
            ],
            is_live=True,
            is_simulated=False
        )
        detector = StaleAnswerDetector(tavily_client=mock_tavily)

        loop = AutonomousCodingLoop(
            workspace_dir=temp_dir,
            task_directive="Fix status code from 200 to 201 in handle_create_item",
            configuration="leancode_tavily",
            stale_detector=detector,
            mock_patch_generator=lambda it, fail, err: """FILE: api_handler.py
<<<<<<< SEARCH
    return {
        "status_code": 200,
        "item": item.model_dump()
    }
=======
    return {
        "status_code": 201,
        "item": item.model_dump()
    }
>>>>>>> REPLACE"""
        )

        summary = loop.run()
        assert summary.tests_passed is True
        # Verify valid Field annotations were preserved in the file
        content = (Path(temp_dir) / "api_handler.py").read_text(encoding="utf-8")
        assert "price: float = Field(" in content

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_uncertain_claims_not_automatically_rewritten():
    """Verify that UNCERTAIN claims are not treated as confirmed deprecations."""
    src = TASKS_DIR / "task_09_uncertain_obscure_math"
    temp_dir = tempfile.mkdtemp(prefix="test_uncertain_")
    try:
        copy_task_files(src, Path(temp_dir))

        # Mock Tavily returning empty evidence -> UNCERTAIN
        mock_tavily = MagicMock(spec=TavilyDocsClient)
        mock_tavily.is_configured = True
        mock_tavily.search_docs.return_value = TavilyVerificationResult(
            query="obscure math",
            evidence_items=[],
            is_live=True,
            is_simulated=False
        )
        detector = StaleAnswerDetector(tavily_client=mock_tavily)

        loop = AutonomousCodingLoop(
            workspace_dir=temp_dir,
            task_directive="Fix base-case bug in _custom_fast_exp when exp is 0",
            configuration="leancode_tavily",
            stale_detector=detector,
            mock_patch_generator=lambda it, fail, err: """FILE: math_internal.py
<<<<<<< SEARCH
    if exp == 0:
        return 0
=======
    if exp == 0:
        return 1
>>>>>>> REPLACE"""
        )

        summary = loop.run()
        assert summary.tests_passed is True
        # Verify custom algorithm was preserved, only bug was fixed
        content = (Path(temp_dir) / "math_internal.py").read_text(encoding="utf-8")
        assert "_custom_fast_exp" in content

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_failed_corrections_trigger_repair(temp_task_dir):
    """Verify that a broken initial patch triggers bounded iterative repair."""
    def multi_iter_gen(iteration, failure, patch_err):
        if iteration == 1:
            # Bad patch that still fails tests
            return """FILE: models.py
<<<<<<< SEARCH
def serialize_user(user: UserProfile) -> dict:
    # Stale/deprecated API usage in Pydantic v2
    return user.dict()
=======
def serialize_user(user: UserProfile) -> dict:
    return {}
>>>>>>> REPLACE"""
        else:
            # Correct patch on iteration 2
            return """FILE: models.py
<<<<<<< SEARCH
def serialize_user(user: UserProfile) -> dict:
    return {}
=======
def serialize_user(user: UserProfile) -> dict:
    return user.model_dump()
>>>>>>> REPLACE"""

    loop = AutonomousCodingLoop(
        workspace_dir=temp_task_dir,
        task_directive="Migrate to model_dump()",
        configuration="leancode",
        mock_patch_generator=multi_iter_gen,
        max_repair_iterations=3
    )

    summary = loop.run()
    assert summary.status == "COMPLETED_VERIFIED"
    assert summary.iterations_count == 2
    assert summary.tests_passed is True

def test_all_three_benchmark_configurations(temp_task_dir):
    """Verify that naive_baseline, leancode, and leancode_tavily run with equal settings."""
    runner = BenchmarkRunner(model_name="gpt-4o-mini", use_deterministic_mocks=True)

    res_a = runner.run_task("task_01_factorial_off_by_one", "naive_baseline")
    res_b = runner.run_task("task_01_factorial_off_by_one", "leancode")
    res_c = runner.run_task("task_01_factorial_off_by_one", "leancode_tavily")

    assert res_a.passed is True
    assert res_b.passed is True
    assert res_c.passed is True
    assert res_a.configuration == "naive_baseline"
    assert res_b.configuration == "leancode"
    assert res_c.configuration == "leancode_tavily"
    assert res_a.model == res_b.model == res_c.model == "gpt-4o-mini"

def test_metrics_separation_in_benchmark():
    """Verify that estimated context tokens are kept separate from provider tokens."""
    runner = BenchmarkRunner(model_name="gpt-4o-mini", use_deterministic_mocks=True)
    res = runner.run_task("task_02_invoice_selective_context", "leancode")

    assert res.total_tokens_spent > 0
    assert res.estimated_context_tokens > 0
    assert res.is_simulated is True

def test_failed_and_incomplete_benchmark_runs():
    """Verify that unfixable or failing tasks produce passed=False without crashing."""
    src = TASKS_DIR / "task_01_factorial_off_by_one"
    temp_dir = tempfile.mkdtemp(prefix="test_fail_")
    try:
        copy_task_files(src, Path(temp_dir))

        # Generator returns completely wrong patch
        def failing_gen(it, fail, err):
            return """FILE: calculator.py
<<<<<<< SEARCH
    for i in range(1, n):
        result *= i
=======
    for i in range(1, 2):
        result = 999
>>>>>>> REPLACE"""

        loop = AutonomousCodingLoop(
            workspace_dir=temp_dir,
            task_directive="Fix factorial bug",
            configuration="leancode",
            mock_patch_generator=failing_gen,
            max_repair_iterations=2
        )

        summary = loop.run()
        assert summary.status in ("FAILED_TESTS", "MAX_ITERATIONS_REACHED")
        assert summary.tests_passed is False
        assert summary.iterations_count == 2

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_reproducible_task_execution():
    """Verify that re-running the same benchmark task produces consistent outcomes."""
    runner = BenchmarkRunner(model_name="gpt-4o-mini", use_deterministic_mocks=True)
    run1 = runner.run_task("task_05_datetime_utcnow_deprecation", "leancode")
    run2 = runner.run_task("task_05_datetime_utcnow_deprecation", "leancode")

    assert run1.passed == run2.passed == True
    assert run1.iterations_count == run2.iterations_count == 1
    assert run1.total_tokens_spent == run2.total_tokens_spent
