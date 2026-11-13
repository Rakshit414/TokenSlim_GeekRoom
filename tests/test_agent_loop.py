"""Test suite for autonomous coding loop (Checkpoint 2).
Validates end-to-end task execution, automatic repair, early stopping,
budget and iteration limits, cancellation, and simulation labeling.
"""
import pytest
import sys
import time
from pathlib import Path
from agent.loop import AutonomousCodingLoop, ExecutionSummary
from agent.bifrost_client import BifrostClient
from server.database import get_connection, init_db

@pytest.fixture
def defect_repo(tmp_path):
    """Creates a small real repository containing a deliberate coding defect and test."""
    calc_code = '''def divide(a: int, b: int) -> float:
    # Operation
    # Deliberate bug: returns 0 instead of division
    return 0.0

def multiply(a: int, b: int) -> int:
    # Operation
    return a * b
'''
    (tmp_path / "calculator.py").write_text(calc_code, encoding="utf-8")

    test_code = '''from calculator import divide, multiply

def test_multiply():
    assert multiply(3, 4) == 12

def test_divide():
    assert divide(10, 2) == 5.0
'''
    (tmp_path / "test_calculator.py").write_text(test_code, encoding="utf-8")
    return tmp_path

def test_successful_autonomous_repair_iteration_1(defect_repo):
    """Verify autonomous repair of a real defect in iteration 1 with early stopping."""
    init_db()

    # Deterministic mock patch generator fixing the divide function
    def mock_patch(iter_idx, failure_summary, patch_err):
        return '''FILE: calculator.py
<<<<<<< SEARCH
def divide(a: int, b: int) -> float:
    # Operation
    # Deliberate bug: returns 0 instead of division
    return 0.0
=======
def divide(a: int, b: int) -> float:
    return a / b
>>>>>>> REPLACE'''

    loop = AutonomousCodingLoop(
        workspace_dir=str(defect_repo),
        task_directive="Fix divide function in calculator.py to return a / b",
        mock_patch_generator=mock_patch,
        test_command=f'"{sys.executable}" -m pytest -v'
    )

    summary = loop.run()

    # Verification:
    assert summary.baseline_test_passed is False
    assert summary.tests_passed is True
    assert summary.status == "COMPLETED_VERIFIED"
    assert summary.iterations_count == 1  # Early stopping on iteration 1
    assert summary.applied_patches_count == 1
    assert summary.is_simulated is True
    assert "divide" in (defect_repo / "calculator.py").read_text(encoding="utf-8")
    assert "return a / b" in (defect_repo / "calculator.py").read_text(encoding="utf-8")

def test_multi_iteration_repair(defect_repo):
    """Verify autonomous error recovery where iteration 1 produces bad code, and iteration 2 repairs it."""
    init_db()

    def two_stage_patch(iter_idx, failure_summary, patch_err):
        if iter_idx == 1:
            # Iteration 1 produces wrong fix
            return '''FILE: calculator.py
<<<<<<< SEARCH
    # Deliberate bug: returns 0 instead of division
    return 0.0
=======
    # Still wrong
    return 2.5
>>>>>>> REPLACE'''
        else:
            # Iteration 2 produces correct fix
            return '''FILE: calculator.py
<<<<<<< SEARCH
    # Still wrong
    return 2.5
=======
    return a / b
>>>>>>> REPLACE'''

    loop = AutonomousCodingLoop(
        workspace_dir=str(defect_repo),
        task_directive="Fix divide bug",
        mock_patch_generator=two_stage_patch,
        test_command=f'"{sys.executable}" -m pytest -v'
    )

    summary = loop.run()

    assert summary.baseline_test_passed is False
    assert summary.tests_passed is True
    assert summary.status == "COMPLETED_VERIFIED"
    assert summary.iterations_count == 2
    assert summary.applied_patches_count == 2

def test_max_repair_iterations_enforcement(defect_repo):
    """Verify that execution stops at max_repair_iterations if defect remains unfixable."""
    init_db()

    # Generator produces repeated failing patches
    def failing_patch(iter_idx, failure_summary, patch_err):
        return f'''FILE: calculator.py
<<<<<<< SEARCH
def divide(a: int, b: int) -> float:
=======
def divide(a: int, b: int) -> float: # attempt {iter_idx}
>>>>>>> REPLACE'''

    loop = AutonomousCodingLoop(
        workspace_dir=str(defect_repo),
        task_directive="Fix divide bug",
        mock_patch_generator=failing_patch,
        max_repair_iterations=3,
        test_command=f'"{sys.executable}" -m pytest -v'
    )

    summary = loop.run()

    assert summary.tests_passed is False
    assert summary.status == "MAX_ITERATIONS_REACHED"
    assert summary.iterations_count == 3

def test_token_budget_enforcement(defect_repo):
    """Verify termination when token budget is exhausted."""
    init_db()

    def any_patch(iter_idx, failure_summary, patch_err):
        return "invalid patch"

    loop = AutonomousCodingLoop(
        workspace_dir=str(defect_repo),
        task_directive="Fix divide bug",
        mock_patch_generator=any_patch,
        token_budget=100,  # Below mock call usage of 200 tokens
        test_command=f'"{sys.executable}" -m pytest -v'
    )

    summary = loop.run()
    # On first loop check or right after first iteration, budget is exhausted
    assert summary.status in ("BUDGET_EXHAUSTED", "MAX_ITERATIONS_REACHED")

def test_cancellation(defect_repo):
    """Verify that cancellation stops the loop cleanly."""
    init_db()

    loop = AutonomousCodingLoop(
        workspace_dir=str(defect_repo),
        task_directive="Fix divide bug",
        test_command=f'"{sys.executable}" -m pytest -v'
    )
    # Cancel immediately
    loop.cancel()
    summary = loop.run()

    assert summary.status == "CANCELLED"
    assert summary.tests_passed is False

def test_patch_rejection_feedback(defect_repo):
    """Verify that ambiguous or stale patch error is recorded and fed back to next iteration."""
    init_db()

    attempt_errors = []

    def ambiguous_then_fix(iter_idx, failure_summary, patch_err):
        attempt_errors.append(patch_err)
        if iter_idx == 1:
            # Produce ambiguous search block '# Operation' that occurs in both functions
            return "FILE: calculator.py\n<<<<<<< SEARCH\n    # Operation\n=======\n    # Operation\n>>>>>>> REPLACE"
        else:
            # Produce exact unique block
            return "FILE: calculator.py\n<<<<<<< SEARCH\ndef divide(a: int, b: int) -> float:\n    # Operation\n    # Deliberate bug: returns 0 instead of division\n    return 0.0\n=======\ndef divide(a: int, b: int) -> float:\n    return a / b\n>>>>>>> REPLACE"

    loop = AutonomousCodingLoop(
        workspace_dir=str(defect_repo),
        task_directive="Fix divide",
        mock_patch_generator=ambiguous_then_fix,
        test_command=f'"{sys.executable}" -m pytest -v'
    )

    summary = loop.run()
    assert summary.tests_passed is True
    assert summary.status == "COMPLETED_VERIFIED"
    assert summary.iterations_count == 2
    # Verify iteration 2 received error from iteration 1
    assert "Ambiguous replacement" in attempt_errors[1]

def test_baseline_pass_but_feature_missing(tmp_path):
    """Verify that agent continues implementation when baseline tests pass but a requested feature is missing."""
    init_db()
    # Math library with only add
    (tmp_path / "math_lib.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    (tmp_path / "test_math.py").write_text("from math_lib import add\ndef test_add(): assert add(1, 2) == 3\n", encoding="utf-8")

    def mock_patch(iter_idx, failure_summary, patch_err):
        return '''FILE: math_lib.py
<<<<<<< SEARCH
def add(a, b): return a + b
=======
def add(a, b): return a + b

def power(base, exp): return base ** exp
>>>>>>> REPLACE'''

    loop = AutonomousCodingLoop(
        workspace_dir=str(tmp_path),
        task_directive="Add function power(base, exp) to math_lib.py",
        mock_patch_generator=mock_patch,
        test_command=f'"{sys.executable}" -m pytest -v'
    )
    summary = loop.run()

    # Did NOT exit early at baseline; applied patch and completed
    assert summary.baseline_test_passed is True
    assert summary.applied_patches_count == 1
    assert summary.status == "COMPLETED_VERIFIED"
    assert "power" in (tmp_path / "math_lib.py").read_text(encoding="utf-8")

def test_baseline_pass_and_task_already_implemented(tmp_path):
    """Verify that agent exits cleanly without redundant edits when requested feature is already implemented."""
    init_db()
    (tmp_path / "math_lib.py").write_text("def add(a, b): return a + b\ndef power(base, exp): return base ** exp\n", encoding="utf-8")
    (tmp_path / "test_math.py").write_text("from math_lib import add, power\ndef test_all(): assert add(1, 2) == 3; assert power(2, 3) == 8\n", encoding="utf-8")

    loop = AutonomousCodingLoop(
        workspace_dir=str(tmp_path),
        task_directive="Verify function power in math_lib.py",
        test_command=f'"{sys.executable}" -m pytest -v'
    )
    summary = loop.run()

    assert summary.baseline_test_passed is True
    assert summary.applied_patches_count == 0  # No redundant edits
    assert summary.status == "COMPLETED_VERIFIED"
    assert summary.iterations_count == 0

def test_time_budget_exhaustion(defect_repo):
    """Verify timeout exhaustion when execution exceeds time_limit_seconds."""
    init_db()

    def slow_patch(iter_idx, failure_summary, patch_err):
        time.sleep(0.3)
        return "invalid"

    loop = AutonomousCodingLoop(
        workspace_dir=str(defect_repo),
        task_directive="Fix divide bug",
        mock_patch_generator=slow_patch,
        time_limit_seconds=0.1,  # Short timeout
        test_command=f'"{sys.executable}" -m pytest -v'
    )
    summary = loop.run()
    assert summary.status == "TIMEOUT_EXCEEDED"

def test_bifrost_gateway_failure(defect_repo):
    """Verify clean handling and error event when Bifrost gateway fails."""
    init_db()
    # Configure Bifrost client with unresolvable host and fallback_mock disabled
    broken_client = BifrostClient(base_url="http://invalid.gateway.local:9999/v1", timeout=0.2)

    loop = AutonomousCodingLoop(
        workspace_dir=str(defect_repo),
        task_directive="Fix divide bug",
        bifrost_client=broken_client,
        test_command=f'"{sys.executable}" -m pytest -v'
    )
    # The BifrostClient will raise ConnectionError if fallback_mock is not passed, but chat_completion defaults fallback_mock=True.
    # Let's test client handling when chat_completion raises an unexpected API error
    broken_client.chat_completion = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("502 Bad Gateway from Bifrost"))

    summary = loop.run()
    assert summary.status == "FAILED"
    assert "502 Bad Gateway" in summary.final_message

def test_sqlite_persistence_and_event_ordering(defect_repo):
    """Verify run status persistence in SQLite and chronological event ordering."""
    init_db()
    run_id = f"test_run_persist_{int(time.time())}"

    def mock_patch(iter_idx, failure_summary, patch_err):
        return '''FILE: calculator.py
<<<<<<< SEARCH
def divide(a: int, b: int) -> float:
    # Operation
    # Deliberate bug: returns 0 instead of division
    return 0.0
=======
def divide(a: int, b: int) -> float:
    return a / b
>>>>>>> REPLACE'''

    loop = AutonomousCodingLoop(
        workspace_dir=str(defect_repo),
        task_directive="Fix divide function",
        mock_patch_generator=mock_patch,
        test_command=f'"{sys.executable}" -m pytest -v',
        run_id=run_id
    )
    summary = loop.run()

    conn = get_connection()
    cursor = conn.cursor()
    # Verify run record in runs table
    row = cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row is not None
    assert row["status"] == "COMPLETED_VERIFIED"
    assert "calculator.py" in row["diff_text"]

    # Verify event ordering
    events = cursor.execute("SELECT event_type FROM run_events WHERE run_id = ? ORDER BY id ASC", (run_id,)).fetchall()
    event_types = [e[0] for e in events]
    assert len(event_types) >= 4
    assert event_types[0] == "start"
    assert "repo_scan" in event_types
    assert "test_baseline" in event_types
    assert event_types[-1] == "finish"
    conn.close()

def test_cancellation_during_active_test(tmp_path):
    """Verify that cancellation reliably terminates an active test subprocess without leakage."""
    init_db()
    # Long running test
    (tmp_path / "test_long.py").write_text("import time\ndef test_sleep(): time.sleep(10)\n", encoding="utf-8")

    import threading

    loop = AutonomousCodingLoop(
        workspace_dir=str(tmp_path),
        task_directive="Run tests",
        test_command=f'"{sys.executable}" -m pytest -v'
    )

    def cancel_after_delay():
        time.sleep(0.4)
        loop.cancel()

    thread = threading.Thread(target=cancel_after_delay)
    thread.start()

    start_t = time.time()
    summary = loop.run()
    elapsed = time.time() - start_t
    thread.join()

    # Must finish well before the 10 second sleep
    assert elapsed < 5.0
    assert summary.status == "CANCELLED"

