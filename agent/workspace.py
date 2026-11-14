"""Secure isolated workspace manager.
Clones target repositories to isolated ephemeral workspaces for safe autonomous execution.
Protects against path traversal, symlink escapes, and unapproved host modification.
"""
import os
import shutil
import tempfile
from pathlib import Path
from typing import Tuple, Set

DEFAULT_WORKSPACE_EXCLUDES = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"
}

def validate_and_resolve_repo_path(repo_path_str: str, base_dir: Path) -> Path:
    """Validate repository path, rejecting path traversal attempts and invalid paths."""
    if not repo_path_str or not repo_path_str.strip():
        raise ValueError("Repository path cannot be empty.")

    if "\x00" in repo_path_str:
        raise ValueError("Null bytes forbidden in repository path.")

    # Reject obvious root traversal attempts
    cleaned = repo_path_str.replace("\\", "/").strip()
    if cleaned.startswith("/") or cleaned.startswith("c:/windows") or cleaned.startswith("c:\\windows"):
        # Forbid targeting sensitive system directories
        lower = cleaned.lower()
        if "windows" in lower or "system32" in lower or "etc" in lower or "usr" in lower:
            raise ValueError(f"Access to sensitive system path forbidden: {repo_path_str}")

    p = Path(repo_path_str)
    if not p.is_absolute():
        p = (base_dir / repo_path_str).resolve()
    else:
        p = p.resolve()

    base_resolved = base_dir.resolve()
    try:
        if not p.is_relative_to(base_resolved):
            raise ValueError(f"Directory traversal detected: path '{repo_path_str}' escapes allowed boundary '{base_resolved}'.")
    except AttributeError:
        if not str(p).startswith(str(base_resolved)):
            raise ValueError(f"Directory traversal detected: path '{repo_path_str}' escapes allowed boundary '{base_resolved}'.")

    if not p.exists():
        raise ValueError(f"Repository directory does not exist: {repo_path_str}")

    if not p.is_dir():
        raise ValueError(f"Repository path is not a directory: {repo_path_str}")

    return p

def create_isolated_workspace(source_repo: Path, prefix: str = "run_ws_") -> Path:
    """Copy source repository into an isolated temporary directory for safe execution."""
    workspaces_root = Path(tempfile.gettempdir()) / "tokenslim_workspaces"
    workspaces_root.mkdir(parents=True, exist_ok=True)

    temp_ws = Path(tempfile.mkdtemp(prefix=prefix, dir=str(workspaces_root))).resolve()

    for item in source_repo.iterdir():
        if item.name in DEFAULT_WORKSPACE_EXCLUDES:
            continue
        dest = temp_ws / item.name
        if item.is_dir():
            shutil.copytree(
                item, dest,
                ignore=shutil.ignore_patterns(*DEFAULT_WORKSPACE_EXCLUDES),
                symlinks=False
            )
        elif item.is_file():
            shutil.copy2(item, dest)

    return temp_ws

def cleanup_isolated_workspace(workspace_path: Path):
    """Safely remove a temporary isolated workspace."""
    try:
        if workspace_path.exists() and "tokenslim_workspaces" in str(workspace_path):
            shutil.rmtree(workspace_path, ignore_errors=True)
    except Exception:
        pass
