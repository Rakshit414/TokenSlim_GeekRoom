"""Test suite for controlled test verification engine (Checkpoint 2).
Validates test execution, exit codes, timeout handling, and failure diagnostic excerpts.
"""
import pytest
import sys
from pathlib import Path
from agent.verification import TestRunner

@pytest.fixture
def test_repo(tmp_path):
    # Create a small repository with a passing and a failing test
    test_file = '''def test_pass():
    assert 1 + 1 == 2

def test_fail():
    val = 10
    assert val == 20, "Value mismatch error"
'''
    (tmp_path / "test_sample.py").write_text(test_file, encoding="utf-8")
    return tmp_path

def test_passing_targeted_test(test_repo):
    """Verify execution of passing test."""
    runner = TestRunner(str(test_repo))
    cmd = f'"{sys.executable}" -m pytest -v "{test_repo / "test_sample.py"}" -k test_pass'
    result = runner.run_tests(test_command=cmd)

    assert result.executed is True
    assert result.passed is True
    assert result.exit_code == 0
    assert "PASS" in result.concise_summary

def test_failing_targeted_test(test_repo):
    """Verify execution of failing test and extraction of concise traceback."""
    runner = TestRunner(str(test_repo))
    cmd = f'"{sys.executable}" -m pytest -v "{test_repo / "test_sample.py"}" -k test_fail'
    result = runner.run_tests(test_command=cmd)

    assert result.executed is True
    assert result.passed is False
    assert result.exit_code != 0
    assert len(result.failing_tests) >= 1
    assert "test_fail" in result.failing_tests[0]
    assert "Value mismatch error" in result.traceback_excerpt
    assert len(result.traceback_excerpt) <= 1000  # Avoid flooded logs

def test_execution_timeout(tmp_path):
    """Verify that hanging tests are cleanly terminated upon reaching timeout limit."""
    hanging_test = '''import time
def test_hang():
    time.sleep(5)
'''
    (tmp_path / "test_hang.py").write_text(hanging_test, encoding="utf-8")
    runner = TestRunner(str(tmp_path), default_timeout_seconds=0.5)
    result = runner.run_tests(target_file="test_hang.py")

    assert result.timed_out is True
    assert result.passed is False
    assert "timed out" in result.concise_summary

def test_invalid_command_handling(tmp_path):
    """Verify graceful handling when test command fails to execute."""
    runner = TestRunner(str(tmp_path))
    result = runner.run_tests(test_command="nonexistent_binary_xyz_123")

    assert result.passed is False
    assert result.exit_code != 0
    assert "not recognized" in result.traceback_excerpt or "FAIL" in result.concise_summary
