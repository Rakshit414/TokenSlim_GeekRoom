"""Minimal patch engine with integrity validation and unified diff generation.
Applies search-and-replace patches safely, rejecting ambiguous, missing, or stale matches.
Preserves unrelated code and records modified line ranges.
"""
import difflib
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from pydantic import BaseModel, Field

class SearchReplaceBlock(BaseModel):
    file_path: str
    search_content: str
    replace_content: str

class PatchResult(BaseModel):
    success: bool
    file_path: str
    original_lines_range: Optional[Tuple[int, int]] = None
    new_lines_range: Optional[Tuple[int, int]] = None
    diff: str = ""
    error_message: Optional[str] = None
    stale_detected: bool = False
    ambiguous_detected: bool = False

class PatchEngine:
    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root).resolve()

    def parse_blocks(self, patch_text: str) -> List[SearchReplaceBlock]:
        """Parse structured search-and-replace blocks from patch text.
        
        Expected format:
        FILE: path/to/file.py
        <<<<<<< SEARCH
        original code
        =======
        replacement code
        >>>>>>> REPLACE
        """
        blocks: List[SearchReplaceBlock] = []
        lines = patch_text.splitlines(keepends=True)
        i = 0
        n = len(lines)

        current_file: Optional[str] = None

        while i < n:
            line = lines[i].strip()
            if line.startswith("FILE:") or line.startswith("*** FILE:"):
                # Extract file path
                parts = line.split(":", 1)
                current_file = parts[1].strip().strip("*").strip()
                i += 1
                continue

            if "<<<<<<< SEARCH" in line:
                if not current_file:
                    i += 1
                    continue

                search_lines = []
                replace_lines = []
                i += 1

                # Gather SEARCH lines until =======
                found_sep = False
                while i < n:
                    if "=======" in lines[i]:
                        found_sep = True
                        i += 1
                        break
                    search_lines.append(lines[i])
                    i += 1

                if not found_sep:
                    # Malformed block: no separator
                    break

                # Gather REPLACE lines until >>>>>>> REPLACE
                found_end = False
                while i < n:
                    if ">>>>>>> REPLACE" in lines[i]:
                        found_end = True
                        i += 1
                        break
                    replace_lines.append(lines[i])
                    i += 1

                if found_end:
                    blocks.append(SearchReplaceBlock(
                        file_path=current_file,
                        search_content="".join(search_lines),
                        replace_content="".join(replace_lines)
                    ))
            else:
                i += 1

        return blocks

    def apply_block(self, block: SearchReplaceBlock) -> PatchResult:
        """Apply a single search-and-replace block with strict boundary and integrity validation."""
        # 1. Path traversal and workspace boundary verification
        try:
            target_path = (self.workspace_root / block.file_path).resolve()
            if not target_path.is_relative_to(self.workspace_root):
                return PatchResult(
                    success=False,
                    file_path=block.file_path,
                    error_message=f"Security violation: path traversal detected outside workspace: {block.file_path}"
                )
        except (ValueError, Exception):
            return PatchResult(
                success=False,
                file_path=block.file_path,
                error_message=f"Security violation: invalid path traversal attempted: {block.file_path}"
            )

        # Check for symlink escaping workspace boundary
        if target_path.is_symlink():
            try:
                real_target = target_path.resolve()
                if not real_target.is_relative_to(self.workspace_root):
                    return PatchResult(
                        success=False,
                        file_path=block.file_path,
                        error_message=f"Security violation: symlink points outside workspace: {block.file_path}"
                    )
            except Exception as e:
                return PatchResult(
                    success=False,
                    file_path=block.file_path,
                    error_message=f"Security violation: unresolvable symlink target: {e}"
                )

        # 2. Target file existence check
        if not target_path.exists():
            return PatchResult(
                success=False,
                file_path=block.file_path,
                error_message=f"Target file does not exist: {block.file_path}"
            )

        if not target_path.is_file():
            return PatchResult(
                success=False,
                file_path=block.file_path,
                error_message=f"Target path is not a file: {block.file_path}"
            )

        # 2. Read original content
        try:
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                original_content = f.read()
        except Exception as e:
            return PatchResult(
                success=False,
                file_path=block.file_path,
                error_message=f"Failed to read file: {e}"
            )

        search_str = block.search_content
        replace_str = block.replace_content

        # Handle empty search string
        if not search_str:
            return PatchResult(
                success=False,
                file_path=block.file_path,
                error_message="Search block cannot be empty"
            )

        # 3. Check occurrences
        occurrences = original_content.count(search_str)

        if occurrences == 0:
            # Check if whitespace differences or slight changes exist (stale patch)
            # Try normalized search to see if it was slightly altered
            norm_orig = " ".join(original_content.split())
            norm_search = " ".join(search_str.split())
            stale = norm_search in norm_orig
            return PatchResult(
                success=False,
                file_path=block.file_path,
                error_message=f"Search block not found in {block.file_path}. Source may have changed since context retrieval.",
                stale_detected=stale
            )

        if occurrences > 1:
            return PatchResult(
                success=False,
                file_path=block.file_path,
                error_message=f"Ambiguous replacement: search block occurs {occurrences} times in {block.file_path}. Specify more surrounding context.",
                ambiguous_detected=True
            )

        # 4. Determine line range of original content
        start_char = original_content.find(search_str)
        end_char = start_char + len(search_str)

        orig_start_line = original_content[:start_char].count("\n") + 1
        orig_end_line = orig_start_line + search_str.count("\n")

        # 5. Apply replacement safely
        new_content = original_content[:start_char] + replace_str + original_content[end_char:]
        new_end_line = orig_start_line + replace_str.count("\n")

        # 6. Generate unified diff
        diff_lines = list(difflib.unified_diff(
            original_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{block.file_path}",
            tofile=f"b/{block.file_path}"
        ))
        diff_str = "".join(diff_lines)

        # 7. Write modified content
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception as e:
            return PatchResult(
                success=False,
                file_path=block.file_path,
                error_message=f"Failed to write patch: {e}"
            )

        return PatchResult(
            success=True,
            file_path=block.file_path,
            original_lines_range=(orig_start_line, orig_end_line),
            new_lines_range=(orig_start_line, new_end_line),
            diff=diff_str
        )

    def apply_patch_text(self, patch_text: str) -> List[PatchResult]:
        """Parse and apply all search-and-replace blocks in a patch text sequentially."""
        blocks = self.parse_blocks(patch_text)
        if not blocks:
            return [PatchResult(
                success=False,
                file_path="",
                error_message="No valid search-and-replace blocks found in patch text."
            )]

        results = []
        for b in blocks:
            res = self.apply_block(b)
            results.append(res)
            if not res.success:
                # Stop immediately if any block fails
                break
        return results
