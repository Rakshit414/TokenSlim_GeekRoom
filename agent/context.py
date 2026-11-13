"""Deterministic selective context retrieval and code slice extractor.
Extracts targeted code slices without sending whole repositories to the LLM.
Handles deduplication, slice merging, context budgeting, and token estimation.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from pydantic import BaseModel, Field

from agent.repository import RepositoryMap, FileMetadata

class CodeSlice(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    content: str
    score: float = 0.0
    matched_reasons: List[str] = Field(default_factory=list)

class ContextMetrics(BaseModel):
    retrieved_files_count: int = 0
    retrieved_slices_count: int = 0
    total_lines: int = 0
    total_characters: int = 0
    estimated_tokens: int = 0
    is_estimated: bool = True
    estimation_method: str = "heuristic_chars_div_4"
    budget_exhausted: bool = False

class ContextPackage(BaseModel):
    query: str
    slices: List[CodeSlice] = Field(default_factory=list)
    metrics: ContextMetrics = Field(default_factory=ContextMetrics)
    formatted_prompt_context: str = ""

def estimate_tokens(text: str) -> Tuple[int, str]:
    """Estimate token count with documented method. Always marked as an estimate."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        tok_count = len(enc.encode(text))
        return tok_count, "tiktoken_cl100k"
    except Exception:
        # Documented standard fallback: 4 characters per token
        tok_count = max(1, len(text) // 4)
        return tok_count, "heuristic_chars_div_4"

class ContextRetriever:
    def __init__(
        self,
        repo_map: RepositoryMap,
        max_tokens: int = 4000,
        max_lines: int = 350,
        max_chars: int = 16000,
        context_window_padding: int = 2
    ):
        self.repo_map = repo_map
        self.root_path = Path(repo_map.root_path)
        self.max_tokens = max_tokens
        self.max_lines = max_lines
        self.max_chars = max_chars
        self.context_window_padding = context_window_padding
        self._rg_path = shutil.which("rg")

    def retrieve(self, query: str) -> ContextPackage:
        """Retrieve minimal, high-relevance code slices deterministically."""
        keywords = self._extract_keywords(query)
        candidate_slices: List[Dict[str, Any]] = []

        # 1. Structural symbol matching from RepositoryMap
        for kw in keywords:
            for file_path, meta in self.repo_map.files.items():
                if meta.is_binary:
                    continue

                # Class matches
                for cls in meta.classes:
                    if kw.lower() == cls.name.lower():
                        candidate_slices.append({
                            "file_path": file_path,
                            "start_line": cls.start_line,
                            "end_line": cls.end_line,
                            "score": 100.0,
                            "reason": f"Exact class match: {cls.name}"
                        })
                    elif kw.lower() in cls.name.lower():
                        candidate_slices.append({
                            "file_path": file_path,
                            "start_line": cls.start_line,
                            "end_line": cls.end_line,
                            "score": 45.0,
                            "reason": f"Partial class match: {cls.name}"
                        })

                # Function and method matches
                for fn in meta.functions:
                    if kw.lower() == fn.name.lower():
                        candidate_slices.append({
                            "file_path": file_path,
                            "start_line": fn.start_line,
                            "end_line": fn.end_line,
                            "score": 90.0,
                            "reason": f"Exact function match: {fn.name}"
                        })
                    elif kw.lower() in fn.name.lower():
                        candidate_slices.append({
                            "file_path": file_path,
                            "start_line": fn.start_line,
                            "end_line": fn.end_line,
                            "score": 40.0,
                            "reason": f"Partial function match: {fn.name}"
                        })

                for cls in meta.classes:
                    for m in cls.methods:
                        if kw.lower() == m.name.lower():
                            candidate_slices.append({
                                "file_path": file_path,
                                "start_line": m.start_line,
                                "end_line": m.end_line,
                                "score": 85.0,
                                "reason": f"Exact method match: {cls.name}.{m.name}"
                            })

                # Import matches
                for imp in meta.imports:
                    if any(kw.lower() == name.lower() for name in imp.imported_names):
                        candidate_slices.append({
                            "file_path": file_path,
                            "start_line": max(1, imp.line - 1),
                            "end_line": imp.line + 1,
                            "score": 30.0,
                            "reason": f"Imported symbol: {kw}"
                        })

                # Filename match
                if kw.lower() in Path(file_path).name.lower():
                    # Reference first 25 lines of directly named file
                    candidate_slices.append({
                        "file_path": file_path,
                        "start_line": 1,
                        "end_line": min(25, meta.line_count or 25),
                        "score": 50.0,
                        "reason": f"Filename match for keyword: {kw}"
                    })

        # 2. Textual pattern search across files
        text_matches = self._search_text(keywords)
        candidate_slices.extend(text_matches)

        # 3. Deduplicate and merge overlapping ranges per file
        merged_slices = self._deduplicate_and_merge(candidate_slices)

        # 4. Deterministic ranking: score desc, file_path asc, start_line asc
        merged_slices.sort(
            key=lambda s: (-s["score"], s["file_path"], s["start_line"])
        )

        # 5. Extract actual file contents and enforce context-size limits
        final_slices: List[CodeSlice] = []
        total_tokens = 0
        total_lines = 0
        total_chars = 0
        budget_exhausted = False
        estimation_method = "heuristic_chars_div_4"

        for item in merged_slices:
            content = self._read_file_lines(
                item["file_path"],
                item["start_line"],
                item["end_line"]
            )
            if not content.strip():
                continue

            slice_lines = item["end_line"] - item["start_line"] + 1
            slice_chars = len(content)
            slice_tokens, method = estimate_tokens(content)
            estimation_method = method

            # Check budgets
            if (total_tokens + slice_tokens > self.max_tokens) or \
               (total_lines + slice_lines > self.max_lines) or \
               (total_chars + slice_chars > self.max_chars):
                budget_exhausted = True
                continue

            final_slices.append(CodeSlice(
                file_path=item["file_path"],
                start_line=item["start_line"],
                end_line=item["end_line"],
                content=content,
                score=item["score"],
                matched_reasons=item.get("reasons", [item.get("reason", "relevance")])
            ))

            total_tokens += slice_tokens
            total_lines += slice_lines
            total_chars += slice_chars

        distinct_files = len(set(s.file_path for s in final_slices))

        metrics = ContextMetrics(
            retrieved_files_count=distinct_files,
            retrieved_slices_count=len(final_slices),
            total_lines=total_lines,
            total_characters=total_chars,
            estimated_tokens=total_tokens,
            is_estimated=True,
            estimation_method=estimation_method,
            budget_exhausted=budget_exhausted
        )

        formatted_context = self._format_slices(final_slices)

        return ContextPackage(
            query=query,
            slices=final_slices,
            metrics=metrics,
            formatted_prompt_context=formatted_context
        )

    def _extract_keywords(self, query: str) -> List[str]:
        """Extract alphanumeric tokens and code identifiers from task query."""
        raw_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", query)
        stopwords = {
            "the", "a", "an", "in", "on", "of", "to", "for", "with", "by",
            "at", "from", "and", "or", "is", "are", "be", "this", "that",
            "fix", "bug", "error", "issue", "test", "tests", "code", "repo"
        }
        keywords = [t for t in raw_tokens if t.lower() not in stopwords and len(t) > 1]
        # Preserve uniqueness while maintaining order
        seen = set()
        res = []
        for kw in keywords:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                res.append(kw)
        return res

    def _search_text(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """Perform deterministic text-based search (pure python scanner)."""
        matches = []
        for file_path, meta in self.repo_map.files.items():
            if meta.is_binary:
                continue

            full_path = self.root_path / file_path
            if not full_path.exists():
                continue

            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    for line_idx, line in enumerate(f, start=1):
                        for kw in keywords:
                            if kw.lower() in line.lower():
                                start = max(1, line_idx - self.context_window_padding)
                                end = min(meta.line_count or line_idx, line_idx + self.context_window_padding)
                                matches.append({
                                    "file_path": file_path,
                                    "start_line": start,
                                    "end_line": end,
                                    "score": 15.0,
                                    "reason": f"Text match for '{kw}' on line {line_idx}"
                                })
            except Exception:
                continue
        return matches

    def _deduplicate_and_merge(self, raw_slices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge adjacent or overlapping line ranges within the same file."""
        if not raw_slices:
            return []

        # Group by file_path
        by_file: Dict[str, List[Dict[str, Any]]] = {}
        for s in raw_slices:
            by_file.setdefault(s["file_path"], []).append(s)

        merged_results: List[Dict[str, Any]] = []

        for file_path, slices in by_file.items():
            # Sort slices by start_line asc, end_line desc
            slices.sort(key=lambda s: (s["start_line"], -s["end_line"]))

            current = None
            for s in slices:
                if current is None:
                    current = {
                        "file_path": file_path,
                        "start_line": s["start_line"],
                        "end_line": s["end_line"],
                        "score": s["score"],
                        "reasons": [s.get("reason", "")]
                    }
                    continue

                # Check overlap or adjacency (within 2 lines)
                if s["start_line"] <= current["end_line"] + 2:
                    current["end_line"] = max(current["end_line"], s["end_line"])
                    current["score"] = max(current["score"], s["score"])
                    if s.get("reason") and s["reason"] not in current["reasons"]:
                        current["reasons"].append(s["reason"])
                else:
                    merged_results.append(current)
                    current = {
                        "file_path": file_path,
                        "start_line": s["start_line"],
                        "end_line": s["end_line"],
                        "score": s["score"],
                        "reasons": [s.get("reason", "")]
                    }
            if current:
                merged_results.append(current)

        return merged_results

    def _read_file_lines(self, rel_path: str, start_line: int, end_line: int) -> str:
        """Read specific line range from a file, adding line numbers."""
        full_path = self.root_path / rel_path
        if not full_path.exists():
            return ""

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            return ""

        selected = lines[max(0, start_line - 1):end_line]
        annotated = []
        current_num = max(1, start_line)
        for line in selected:
            annotated.append(f"{current_num:4d} | {line.rstrip()}")
            current_num += 1

        return "\n".join(annotated)

    def _format_slices(self, slices: List[CodeSlice]) -> str:
        """Format slices into structured prompt context."""
        if not slices:
            return "// No specific context retrieved."

        blocks = []
        for s in slices:
            header = f"--- File: {s.file_path} (Lines {s.start_line}-{s.end_line}) ---"
            reasons = f"// Relevant: {', '.join(s.matched_reasons)}"
            blocks.append(f"{header}\n{reasons}\n{s.content}\n")
        return "\n".join(blocks)
