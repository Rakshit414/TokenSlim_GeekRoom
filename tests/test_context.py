"""Test suite for selective context retrieval and code slice extractor (Checkpoint 1).
Validates targeted retrieval, deduplication, slice merging, context budgeting, and token estimation.
"""
import pytest
from pathlib import Path
from agent.repository import RepositoryScanner
from agent.context import ContextRetriever, estimate_tokens

@pytest.fixture
def sample_repo(tmp_path):
    """Creates a sample multi-file repository with relevant and irrelevant code."""
    # Module with target class and methods
    auth_code = '''"""Authentication and token validation."""
import datetime

class AuthManager:
    """Manages user sessions and token validation."""
    def __init__(self, secret_key: str):
        self.secret_key = secret_key

    def validate_token(self, token: str) -> bool:
        if not token:
            return False
        return token.startswith("valid_")

    def revoke_token(self, token: str) -> None:
        pass
'''
    (tmp_path / "auth.py").write_text(auth_code, encoding="utf-8")

    # Module with database logic
    db_code = '''"""Database access layer."""
class DatabaseConnection:
    def connect(self):
        return True

def query_users(limit: int = 100):
    """Fetch user accounts."""
    return [{"id": i} for i in range(limit)]
'''
    (tmp_path / "database.py").write_text(db_code, encoding="utf-8")

    # Irrelevant file with unrelated content
    unrelated_code = '''"""Unrelated reporting utilities."""
def generate_annual_report():
    return "Report Content"

class FinancialMetrics:
    def compute(self):
        return 0.0
'''
    (tmp_path / "reports.py").write_text(unrelated_code, encoding="utf-8")

    return tmp_path

def test_relevant_code_retrieval(sample_repo):
    """Verify targeted retrieval of AuthManager and validate_token without pulling unrelated files."""
    scanner = RepositoryScanner(str(sample_repo))
    repo_map = scanner.scan()

    retriever = ContextRetriever(repo_map, max_tokens=2000)
    package = retriever.retrieve("Fix bug in validate_token method inside AuthManager")

    assert len(package.slices) > 0
    retrieved_files = {s.file_path for s in package.slices}
    assert "auth.py" in retrieved_files
    # reports.py should NOT be retrieved
    assert "reports.py" not in retrieved_files

    # Check slice content contains target method
    auth_content = "\n".join(s.content for s in package.slices if s.file_path == "auth.py")
    assert "def validate_token" in auth_content
    assert "AuthManager" in auth_content

def test_slice_deduplication_and_merging(sample_repo):
    """Verify that multiple keyword matches within adjacent lines merge into a single slice."""
    scanner = RepositoryScanner(str(sample_repo))
    repo_map = scanner.scan()

    retriever = ContextRetriever(repo_map, context_window_padding=3)
    # Query mentions multiple symbols inside AuthManager in auth.py
    package = retriever.retrieve("AuthManager secret_key validate_token revoke_token")

    # There should be merged slices rather than one slice per token
    auth_slices = [s for s in package.slices if s.file_path == "auth.py"]
    assert len(auth_slices) <= 2
    # Verify no two slices in the same file overlap
    for i in range(len(auth_slices)):
        for j in range(i + 1, len(auth_slices)):
            s1, s2 = auth_slices[i], auth_slices[j]
            assert s1.end_line < s2.start_line or s2.end_line < s1.start_line

def test_context_budget_limits(sample_repo):
    """Verify that retrieval strictly respects max_tokens and flags budget_exhausted when truncated."""
    scanner = RepositoryScanner(str(sample_repo))
    repo_map = scanner.scan()

    # Extremely low limit: max 25 tokens (~100 chars)
    tiny_retriever = ContextRetriever(repo_map, max_tokens=25, max_lines=5)
    package = tiny_retriever.retrieve("AuthManager DatabaseConnection query_users generate_annual_report")

    assert package.metrics.estimated_tokens <= 25
    assert package.metrics.total_lines <= 5
    assert package.metrics.budget_exhausted is True

def test_token_estimation_utility():
    """Verify documented token estimation and clear marking as estimate."""
    text = "def hello_world(): return 'Hello, World!'"
    count, method = estimate_tokens(text)
    assert count > 0
    assert method in ("tiktoken_cl100k", "heuristic_chars_div_4")

def test_deterministic_retrieval(sample_repo):
    """Verify that repeated retrievals with the same query produce bit-for-bit identical results."""
    scanner = RepositoryScanner(str(sample_repo))
    repo_map = scanner.scan()
    retriever = ContextRetriever(repo_map)

    query = "User authentication token validation query_users"
    res1 = retriever.retrieve(query)
    res2 = retriever.retrieve(query)

    assert res1.model_dump() == res2.model_dump()
    assert res1.formatted_prompt_context == res2.formatted_prompt_context
