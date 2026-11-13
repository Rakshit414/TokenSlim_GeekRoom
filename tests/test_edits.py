"""Test suite for minimal patch engine (Checkpoint 2).
Validates exact search-and-replace, ambiguous matches, stale patches, missing files, and formatting preservation.
"""
import pytest
from pathlib import Path
from agent.edits import PatchEngine, SearchReplaceBlock

@pytest.fixture
def workspace(tmp_path):
    code = '''def greet(name: str) -> str:
    # Initial greeting
    return "Hello, " + name

def add(a: int, b: int) -> int:
    return a + b
'''
    (tmp_path / "utils.py").write_text(code, encoding="utf-8")
    return tmp_path

def test_successful_patch(workspace):
    """Verify clean application of exact search-and-replace patch."""
    engine = PatchEngine(str(workspace))
    patch = '''FILE: utils.py
<<<<<<< SEARCH
def add(a: int, b: int) -> int:
    return a + b
=======
def add(a: int, b: int) -> int:
    # Adds two integers
    return a + b
>>>>>>> REPLACE'''

    results = engine.apply_patch_text(patch)
    assert len(results) == 1
    res = results[0]
    assert res.success is True
    assert res.file_path == "utils.py"
    assert "Adds two integers" in (workspace / "utils.py").read_text(encoding="utf-8")
    assert "def greet" in (workspace / "utils.py").read_text(encoding="utf-8")  # Unrelated code preserved

def test_missing_target_file(workspace):
    """Verify clear error when target file does not exist."""
    engine = PatchEngine(str(workspace))
    patch = '''FILE: nonexistent.py
<<<<<<< SEARCH
foo
=======
bar
>>>>>>> REPLACE'''

    results = engine.apply_patch_text(patch)
    assert len(results) == 1
    assert results[0].success is False
    assert "Target file does not exist" in results[0].error_message

def test_ambiguous_replacement_rejection(workspace):
    """Verify rejection when search block matches multiple locations."""
    code = '''item = 1
# first occurrence
print(item)
# second occurrence
print(item)
'''
    (workspace / "ambiguous.py").write_text(code, encoding="utf-8")

    engine = PatchEngine(str(workspace))
    patch = '''FILE: ambiguous.py
<<<<<<< SEARCH
print(item)
=======
print(item + 1)
>>>>>>> REPLACE'''

    results = engine.apply_patch_text(patch)
    assert len(results) == 1
    assert results[0].success is False
    assert results[0].ambiguous_detected is True
    assert "Ambiguous replacement: search block occurs 2 times" in results[0].error_message

def test_stale_patch_rejection(workspace):
    """Verify error when search block cannot be found in target file."""
    engine = PatchEngine(str(workspace))
    patch = '''FILE: utils.py
<<<<<<< SEARCH
def subtract(a: int, b: int) -> int:
    return a - b
=======
def subtract(a: int, b: int) -> int:
    return a - b - 1
>>>>>>> REPLACE'''

    results = engine.apply_patch_text(patch)
    assert len(results) == 1
    assert results[0].success is False
    assert "Search block not found" in results[0].error_message

def test_preservation_of_unrelated_code(workspace):
    """Verify unrelated formatting, comments, and functions remain intact."""
    engine = PatchEngine(str(workspace))
    orig_text = (workspace / "utils.py").read_text(encoding="utf-8")

    patch = '''FILE: utils.py
<<<<<<< SEARCH
    # Initial greeting
    return "Hello, " + name
=======
    # Updated greeting
    return f"Welcome, {name}!"
>>>>>>> REPLACE'''

    results = engine.apply_patch_text(patch)
    assert results[0].success is True
    new_text = (workspace / "utils.py").read_text(encoding="utf-8")

    assert "def add(a: int, b: int) -> int:\n    return a + b" in new_text
    assert "Welcome" in new_text

def test_empty_or_malformed_patch(workspace):
    """Verify handling of empty or malformed patch text."""
    engine = PatchEngine(str(workspace))
    res_empty = engine.apply_patch_text("random text without blocks")
    assert len(res_empty) == 1
    assert res_empty[0].success is False
    assert "No valid search-and-replace blocks" in res_empty[0].error_message
