"""Test suite for repository intelligence and AST scanner (Checkpoint 1).
Validates symbol extraction, line ranges, error handling, exclusions, and fallbacks.
"""
import pytest
from pathlib import Path
from agent.repository import RepositoryScanner, RepositoryMap

def test_empty_repository(tmp_path):
    """Verify that scanning an empty repository produces an empty map without error."""
    scanner = RepositoryScanner(str(tmp_path))
    repo_map = scanner.scan()
    assert repo_map.total_files == 0
    assert repo_map.total_python_files == 0
    assert repo_map.total_lines == 0
    assert len(repo_map.files) == 0

def test_python_ast_extraction(tmp_path):
    """Verify extraction of imports, functions, classes, methods, docstrings, and signatures."""
    sample_code = '''"""Module docstring."""
import os
import sys as system
from typing import List, Optional
from mypkg.utils import helper_fn

GLOBAL_CONFIG = {"key": "val"}

def calculate_metric(a: int, b: float = 1.0) -> float:
    """Calculate metric docstring."""
    return a * b

async def fetch_async(url: str):
    pass

class DataProcessor(object):
    """Class docstring."""
    def __init__(self, name: str):
        self.name = name

    def process(self, items: List[int]) -> int:
        return sum(items)
'''
    py_file = tmp_path / "processor.py"
    py_file.write_text(sample_code, encoding="utf-8")

    scanner = RepositoryScanner(str(tmp_path))
    repo_map = scanner.scan()

    assert "processor.py" in repo_map.files
    meta = repo_map.files["processor.py"]
    assert meta.language == "python"
    assert not meta.has_syntax_error
    assert meta.line_count > 15

    # Verify functions
    func_names = [f.name for f in meta.functions]
    assert "calculate_metric" in func_names
    assert "fetch_async" in func_names

    calc_fn = next(f for f in meta.functions if f.name == "calculate_metric")
    assert "calculate_metric" in calc_fn.signature
    assert "a: int" in calc_fn.signature
    assert "b: float" in calc_fn.signature
    assert "-> float" in calc_fn.signature
    assert calc_fn.docstring == "Calculate metric docstring."
    assert calc_fn.start_line == 9
    assert calc_fn.end_line == 11
    assert not calc_fn.is_async

    async_fn = next(f for f in meta.functions if f.name == "fetch_async")
    assert async_fn.is_async
    assert "async def fetch_async" in async_fn.signature

    # Verify classes and methods
    assert len(meta.classes) == 1
    cls_def = meta.classes[0]
    assert cls_def.name == "DataProcessor"
    assert cls_def.docstring == "Class docstring."
    assert len(cls_def.methods) == 2
    method_names = [m.name for m in cls_def.methods]
    assert "__init__" in method_names
    assert "process" in method_names

    # Verify imports
    import_mods = [i.module for i in meta.imports]
    assert "os" in import_mods
    assert "typing" in import_mods
    assert "mypkg.utils" in import_mods

    # Verify top-level symbols
    assert "GLOBAL_CONFIG" in meta.top_level_symbols

def test_syntax_error_resilience(tmp_path):
    """Verify that a malformed Python file does not crash the scan and records syntax error."""
    broken_code = '''def broken_function(:
    print("Invalid syntax"
'''
    valid_code = '''def valid_function():
    return 42
'''
    (tmp_path / "broken.py").write_text(broken_code, encoding="utf-8")
    (tmp_path / "valid.py").write_text(valid_code, encoding="utf-8")

    scanner = RepositoryScanner(str(tmp_path))
    repo_map = scanner.scan()

    assert repo_map.total_files == 2
    broken_meta = repo_map.files["broken.py"]
    assert broken_meta.has_syntax_error
    assert "SyntaxError" in (broken_meta.syntax_error_message or "")

    valid_meta = repo_map.files["valid.py"]
    assert not valid_meta.has_syntax_error
    assert len(valid_meta.functions) == 1

def test_directory_and_binary_exclusions(tmp_path):
    """Verify that excluded directories (.git, node_modules, .venv) and binary files are ignored/detected."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("git config", encoding="utf-8")

    venv_dir = tmp_path / ".venv" / "lib"
    venv_dir.mkdir(parents=True)
    (venv_dir / "dep.py").write_text("def lib(): pass", encoding="utf-8")

    node_dir = tmp_path / "node_modules"
    node_dir.mkdir()
    (node_dir / "pkg.js").write_text("console.log()", encoding="utf-8")

    # Binary file
    bin_file = tmp_path / "image.png"
    bin_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00")

    # Valid source file
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")

    scanner = RepositoryScanner(str(tmp_path))
    repo_map = scanner.scan()

    assert "main.py" in repo_map.files
    # Excluded directories must NOT be in files
    assert not any(p.startswith(".git") for p in repo_map.files)
    assert not any(p.startswith(".venv") for p in repo_map.files)
    assert not any(p.startswith("node_modules") for p in repo_map.files)

    # Binary file excluded or flagged binary
    if "image.png" in repo_map.files:
        assert repo_map.files["image.png"].is_binary

def test_non_python_fallback(tmp_path):
    """Verify metadata collection for non-Python text files (JS, JSON, MD)."""
    (tmp_path / "readme.md").write_text("# Project\nOverview description.", encoding="utf-8")
    (tmp_path / "config.json").write_text('{"debug": true}\n', encoding="utf-8")
    (tmp_path / "script.js").write_text("function run() { return 1; }\n", encoding="utf-8")

    scanner = RepositoryScanner(str(tmp_path))
    repo_map = scanner.scan()

    assert "readme.md" in repo_map.files
    assert repo_map.files["readme.md"].language == "markdown"
    assert repo_map.files["readme.md"].line_count == 2

    assert "config.json" in repo_map.files
    assert repo_map.files["config.json"].language == "json"

    assert "script.js" in repo_map.files
    assert repo_map.files["script.js"].language == "javascript"

def test_find_symbol_lookup(tmp_path):
    """Verify that find_symbol reliably locates functions and classes across modules."""
    (tmp_path / "mod_a.py").write_text("def target_fn(): return 1\n", encoding="utf-8")
    (tmp_path / "mod_b.py").write_text("class TargetClass:\n    def target_method(self): pass\n", encoding="utf-8")

    scanner = RepositoryScanner(str(tmp_path))
    repo_map = scanner.scan()

    fn_matches = repo_map.find_symbol("target_fn")
    assert len(fn_matches) == 1
    assert fn_matches[0]["file_path"] == "mod_a.py"
    assert fn_matches[0]["type"] == "function"

    cls_matches = repo_map.find_symbol("TargetClass")
    assert len(cls_matches) == 1
    assert cls_matches[0]["file_path"] == "mod_b.py"
    assert cls_matches[0]["type"] == "class"

    method_matches = repo_map.find_symbol("target_method")
    assert len(method_matches) == 1
    assert method_matches[0]["file_path"] == "mod_b.py"
    assert method_matches[0]["type"] == "method"

def test_deterministic_scan_consistency(tmp_path):
    """Verify that multiple scans on the same repo produce 100% identical outputs."""
    for i in range(5):
        (tmp_path / f"file_{i}.py").write_text(f"def fn_{i}(): pass\n", encoding="utf-8")

    scanner = RepositoryScanner(str(tmp_path))
    map1 = scanner.scan()
    map2 = scanner.scan()

    assert map1.model_dump() == map2.model_dump()
