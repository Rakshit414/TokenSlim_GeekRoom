"""Lightweight AST-based repository scanner and structural mapper.
Extracts symbols, classes, functions, signatures, line ranges, and module dependencies.
Provides non-Python fallback metadata and robust error handling.
"""
import ast
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
from pydantic import BaseModel, Field

DEFAULT_EXCLUDED_DIRS: Set[str] = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "build",
    "dist",
    ".eggs",
    ".idea",
    ".vscode",
    "traces",
    "data"
}

DEFAULT_EXCLUDED_EXTENSIONS: Set[str] = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".zip",
    ".tar", ".gz", ".db", ".sqlite", ".sqlite3", ".woff", ".woff2"
}

# Resource limit thresholds for safe scanning
MAX_FILE_BYTES: int = 500 * 1024  # 500 KB limit per file
MAX_SCAN_BYTES: int = 20 * 1024 * 1024  # 20 MB total scan limit
MAX_FILES_COUNT: int = 1000  # Max total files scanned

class FunctionDef(BaseModel):
    name: str
    signature: str
    docstring: Optional[str] = None
    start_line: int
    end_line: int
    is_async: bool = False
    decorators: List[str] = Field(default_factory=list)

class ClassDef(BaseModel):
    name: str
    docstring: Optional[str] = None
    bases: List[str] = Field(default_factory=list)
    start_line: int
    end_line: int
    methods: List[FunctionDef] = Field(default_factory=list)

class ImportDef(BaseModel):
    module: str
    imported_names: List[str] = Field(default_factory=list)
    alias: Optional[str] = None
    line: int = 1
    is_from: bool = False

class FileMetadata(BaseModel):
    path: str
    language: str
    size_bytes: int
    line_count: int
    is_binary: bool = False
    has_syntax_error: bool = False
    syntax_error_message: Optional[str] = None
    classes: List[ClassDef] = Field(default_factory=list)
    functions: List[FunctionDef] = Field(default_factory=list)
    imports: List[ImportDef] = Field(default_factory=list)
    top_level_symbols: List[str] = Field(default_factory=list)

class RepositoryMap(BaseModel):
    root_path: str
    files: Dict[str, FileMetadata] = Field(default_factory=dict)
    internal_modules: List[str] = Field(default_factory=list)
    total_files: int = 0
    total_python_files: int = 0
    total_lines: int = 0

    def find_symbol(self, symbol_name: str) -> List[Dict[str, Any]]:
        """Locate any function, class, or method matching symbol_name across all files."""
        matches = []
        for file_path, meta in self.files.items():
            for fn in meta.functions:
                if fn.name == symbol_name:
                    matches.append({
                        "file_path": file_path,
                        "type": "function",
                        "name": fn.name,
                        "signature": fn.signature,
                        "start_line": fn.start_line,
                        "end_line": fn.end_line
                    })
            for cls in meta.classes:
                if cls.name == symbol_name:
                    matches.append({
                        "file_path": file_path,
                        "type": "class",
                        "name": cls.name,
                        "bases": cls.bases,
                        "start_line": cls.start_line,
                        "end_line": cls.end_line
                    })
                for m in cls.methods:
                    if m.name == symbol_name:
                        matches.append({
                            "file_path": file_path,
                            "type": "method",
                            "class_name": cls.name,
                            "name": m.name,
                            "signature": m.signature,
                            "start_line": m.start_line,
                            "end_line": m.end_line
                        })
        return matches

    def get_dependencies_graph(self) -> Dict[str, List[str]]:
        """Map dependencies between internal modules in the repository."""
        graph: Dict[str, List[str]] = {}
        for file_path, meta in self.files.items():
            deps = set()
            for imp in meta.imports:
                for int_mod in self.internal_modules:
                    if imp.module == int_mod or imp.module.startswith(int_mod + "."):
                        deps.add(int_mod)
            graph[file_path] = sorted(list(deps))
        return graph


class RepositoryScanner:
    def __init__(
        self,
        repo_path: str,
        exclude_dirs: Optional[Set[str]] = None,
        exclude_extensions: Optional[Set[str]] = None,
        max_file_size_bytes: int = 500 * 1024,  # 500KB limit per individual file
        max_repo_bytes: int = 20 * 1024 * 1024,  # 20MB limit total scanned repo
        max_total_files: int = 1000  # Max files to scan to prevent exhaustion
    ):
        self.root_path = Path(repo_path).resolve()
        self.exclude_dirs = set(DEFAULT_EXCLUDED_DIRS)
        if exclude_dirs:
            self.exclude_dirs.update(exclude_dirs)
        self.exclude_extensions = set(DEFAULT_EXCLUDED_EXTENSIONS)
        if exclude_extensions:
            self.exclude_extensions.update(exclude_extensions)
        self.max_file_size_bytes = max_file_size_bytes
        self.max_repo_bytes = max_repo_bytes
        self.max_total_files = max_total_files

    def is_binary_file(self, file_path: Path) -> bool:
        """Heuristic check to detect binary files safely."""
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(1024)
                if b"\0" in chunk:
                    return True
                # Attempt decoding
                chunk.decode("utf-8")
                return False
        except UnicodeDecodeError:
            return True
        except Exception:
            return True

    def scan(self) -> RepositoryMap:
        """Scan repository safely and build a lightweight structural RepositoryMap."""
        files_map: Dict[str, FileMetadata] = {}
        internal_modules: Set[str] = set()
        total_scanned_bytes = 0

        if not self.root_path.exists():
            return RepositoryMap(root_path=str(self.root_path))

        # First pass: collect files and identify internal module candidates
        for root, dirs, files in os.walk(self.root_path):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in self.exclude_dirs and not d.startswith(".")]

            rel_dir = Path(root).relative_to(self.root_path)

            for file_name in files:
                if len(files_map) >= self.max_total_files:
                    break

                file_ext = os.path.splitext(file_name)[1].lower()
                if file_ext in self.exclude_extensions:
                    continue

                full_path = Path(root) / file_name

                # Symlink escape protection: ensure target resolves within root_path
                if full_path.is_symlink():
                    try:
                        resolved_target = full_path.resolve()
                        if not resolved_target.is_relative_to(self.root_path):
                            continue
                    except Exception:
                        continue

                try:
                    file_size = full_path.stat().st_size
                except Exception:
                    file_size = 0

                # Skip files exceeding individual file size limit (500KB)
                if file_size > self.max_file_size_bytes:
                    continue

                # Enforce cumulative repository size limit (20MB)
                if total_scanned_bytes + file_size > self.max_repo_bytes:
                    raise ValueError(f"Repository scan exceeds maximum allowed limit of {self.max_repo_bytes} bytes.")
                total_scanned_bytes += file_size

                rel_path = str((rel_dir / file_name).as_posix())

                # Track internal module names
                if file_ext == ".py":
                    mod_name = rel_path[:-3].replace("/", ".").replace("\\", ".")
                    if mod_name.endswith(".__init__"):
                        mod_name = mod_name[:-9]
                    internal_modules.add(mod_name)
                    top_mod = mod_name.split(".")[0]
                    internal_modules.add(top_mod)

                meta = self._analyze_file(full_path, rel_path, file_ext)
                files_map[rel_path] = meta

            if total_scanned_bytes >= self.max_repo_bytes or len(files_map) >= self.max_total_files:
                break

        total_lines = sum(f.line_count for f in files_map.values())
        total_py = sum(1 for f in files_map.values() if f.language == "python")

        return RepositoryMap(
            root_path=str(self.root_path),
            files=files_map,
            internal_modules=sorted(list(internal_modules)),
            total_files=len(files_map),
            total_python_files=total_py,
            total_lines=total_lines
        )

    def _analyze_file(self, full_path: Path, rel_path: str, ext: str) -> FileMetadata:
        """Analyze a single file with AST if Python, or fallback metadata."""
        try:
            stat = full_path.stat()
            size = stat.st_size
        except Exception:
            size = 0

        # Check binary
        if self.is_binary_file(full_path) or ext in self.exclude_extensions:
            return FileMetadata(
                path=rel_path,
                language="binary",
                size_bytes=size,
                line_count=0,
                is_binary=True
            )

        # Non-Python text fallback
        if ext != ".py":
            line_count = 0
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    line_count = sum(1 for _ in f)
            except Exception:
                pass

            lang = "javascript" if ext in (".js", ".jsx", ".ts", ".tsx") else \
                   "json" if ext == ".json" else \
                   "markdown" if ext in (".md", ".markdown") else \
                   "html" if ext in (".html", ".htm") else \
                   "css" if ext == ".css" else \
                   "yaml" if ext in (".yml", ".yaml") else "text"

            return FileMetadata(
                path=rel_path,
                language=lang,
                size_bytes=size,
                line_count=line_count,
                is_binary=False
            )

        # Python file: parse AST
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            lines = content.splitlines()
            line_count = len(lines)
        except Exception as e:
            return FileMetadata(
                path=rel_path,
                language="python",
                size_bytes=size,
                line_count=0,
                has_syntax_error=True,
                syntax_error_message=f"Read error: {e}"
            )

        try:
            tree = ast.parse(content, filename=rel_path)
        except SyntaxError as syn_err:
            return FileMetadata(
                path=rel_path,
                language="python",
                size_bytes=size,
                line_count=line_count,
                has_syntax_error=True,
                syntax_error_message=f"SyntaxError at line {syn_err.lineno}: {syn_err.msg}"
            )
        except Exception as gen_err:
            return FileMetadata(
                path=rel_path,
                language="python",
                size_bytes=size,
                line_count=line_count,
                has_syntax_error=True,
                syntax_error_message=f"Parse error: {gen_err}"
            )

        classes: List[ClassDef] = []
        functions: List[FunctionDef] = []
        imports: List[ImportDef] = []
        top_level_symbols: List[str] = []

        for node in tree.body:
            # Imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(ImportDef(
                        module=alias.name,
                        imported_names=[alias.name],
                        alias=alias.asname,
                        line=node.lineno,
                        is_from=False
                    ))
            elif isinstance(node, ast.ImportFrom):
                mod_name = node.module or ""
                names = [n.name for n in node.names]
                imports.append(ImportDef(
                    module=mod_name,
                    imported_names=names,
                    line=node.lineno,
                    is_from=True
                ))

            # Top-level Functions
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_def = self._parse_function_node(node)
                functions.append(fn_def)
                top_level_symbols.append(node.name)

            # Classes
            elif isinstance(node, ast.ClassDef):
                cls_def = self._parse_class_node(node)
                classes.append(cls_def)
                top_level_symbols.append(node.name)

            # Top-level Variable / Constant assignments
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        top_level_symbols.append(target.id)
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    top_level_symbols.append(node.target.id)

        return FileMetadata(
            path=rel_path,
            language="python",
            size_bytes=size,
            line_count=line_count,
            has_syntax_error=False,
            classes=classes,
            functions=functions,
            imports=imports,
            top_level_symbols=top_level_symbols
        )

    def _parse_function_node(self, node: ast.AST) -> FunctionDef:
        """Reconstruct function signature, line range, and docstring."""
        name = getattr(node, "name", "anonymous")
        is_async = isinstance(node, ast.AsyncFunctionDef)
        start_line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", start_line)
        docstring = ast.get_docstring(node)

        # Format decorators
        decorators = []
        for dec in getattr(node, "decorator_list", []):
            try:
                decorators.append("@" + ast.unparse(dec))
            except Exception:
                decorators.append("@decorator")

        # Format signature
        try:
            args_str = ast.unparse(node.args)
        except Exception:
            args_str = "..."

        ret_str = ""
        if getattr(node, "returns", None):
            try:
                ret_str = f" -> {ast.unparse(node.returns)}"
            except Exception:
                pass

        prefix = "async def " if is_async else "def "
        signature = f"{prefix}{name}({args_str}){ret_str}"

        return FunctionDef(
            name=name,
            signature=signature,
            docstring=docstring,
            start_line=start_line,
            end_line=end_line,
            is_async=is_async,
            decorators=decorators
        )

    def _parse_class_node(self, node: ast.ClassDef) -> ClassDef:
        """Parse class definition, inheritance bases, and inner methods."""
        start_line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", start_line)
        docstring = ast.get_docstring(node)

        bases: List[str] = []
        for base in node.bases:
            try:
                bases.append(ast.unparse(base))
            except Exception:
                bases.append("base")

        methods: List[FunctionDef] = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(self._parse_function_node(item))

        return ClassDef(
            name=node.name,
            docstring=docstring,
            bases=bases,
            start_line=start_line,
            end_line=end_line,
            methods=methods
        )
