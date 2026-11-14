"""Controlled test execution and failure excerpt extractor.
Runs targeted tests within an isolated workspace with timeouts and cancellation.
Extracts concise failure summaries and tracebacks without flooding LLM context.
"""
import os
import re
import sys
import time
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from pydantic import BaseModel, Field

class TestExecutionResult(BaseModel):
    __test__ = False
    command: str
    exit_code: int
    passed: bool
    duration_seconds: float
    concise_summary: str
    failing_tests: List[str] = Field(default_factory=list)
    traceback_excerpt: str = ""
    raw_output_truncated: str = ""
    executed: bool = True
    timed_out: bool = False
    cancelled: bool = False

def is_process_alive(pid: int) -> bool:
    """Check if a process is still actively running on the operating system."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return exit_code.value == STILL_ACTIVE
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

def kill_process_tree(pid: int):
    """Safely terminate a process and all its child processes to prevent process leakage."""
    if pid <= 0:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(
                f"taskkill /F /T /PID {pid}",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0
            )
        except Exception:
            pass
    else:
        try:
            import signal
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, 9)
            except Exception:
                pass

class TestRunner:
    __test__ = False
    def __init__(
        self,
        workspace_dir: str,
        python_executable: Optional[str] = None,
        default_timeout_seconds: float = 25.0,
        max_log_chars: int = 2000
    ):
        self.workspace_dir = Path(workspace_dir).resolve()
        self.python_executable = python_executable or sys.executable
        self.default_timeout_seconds = default_timeout_seconds
        self.max_log_chars = max_log_chars
        self._active_process: Optional[subprocess.Popen] = None
        self._cancelled: bool = False

    def cancel_active(self):
        """Signal cancellation and terminate any running test process tree immediately."""
        self._cancelled = True
        if self._active_process and self._active_process.poll() is None:
            kill_process_tree(self._active_process.pid)
            try:
                self._active_process.kill()
            except Exception:
                pass

    def run_tests(
        self,
        test_command: Optional[str] = None,
        target_file: Optional[str] = None,
        timeout: Optional[float] = None
    ) -> TestExecutionResult:
        """Execute tests in workspace and return concise, actionable results."""
        timeout_sec = timeout or self.default_timeout_seconds

        # Build safe test command
        shell_execution = False
        if test_command:
            if any(op in test_command for op in ("&&", "||", ";", "|", ">", "<")):
                cmd = test_command
                shell_execution = True
            else:
                import shlex
                try:
                    tokens = shlex.split(test_command, posix=(sys.platform != "win32"))
                    cmd = [t.strip('"\'') for t in tokens]
                except Exception:
                    cmd = test_command
                    shell_execution = True
        elif target_file:
            cmd = [self.python_executable, "-m", "pytest", "-v", str(target_file)]
        else:
            cmd = [self.python_executable, "-m", "pytest", "-v"]

        start_time = time.time()
        self._active_process = None

        cmd_display = cmd if isinstance(cmd, str) else " ".join(cmd)

        if self._cancelled:
            return TestExecutionResult(
                command=cmd_display,
                exit_code=-3,
                passed=False,
                duration_seconds=0.0,
                concise_summary="Test execution cancelled prior to launch.",
                executed=False,
                timed_out=False,
                cancelled=True
            )

        try:
            # Run in workspace directory with isolated environment
            env = os.environ.copy()
            # Ensure workspace is at front of PYTHONPATH
            env["PYTHONPATH"] = str(self.workspace_dir) + os.pathsep + env.get("PYTHONPATH", "")

            process = subprocess.Popen(
                cmd,
                shell=shell_execution,
                cwd=str(self.workspace_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )
            self._active_process = process

            stdout, stderr = process.communicate(timeout=timeout_sec)
            elapsed = time.time() - start_time
            exit_code = process.returncode
            self._active_process = None

            if self._cancelled:
                return TestExecutionResult(
                    command=cmd_display,
                    exit_code=-3,
                    passed=False,
                    duration_seconds=elapsed,
                    concise_summary="Test execution cancelled during run.",
                    executed=True,
                    timed_out=False,
                    cancelled=True
                )

            combined_output = (stdout or "") + ("\n" + stderr if stderr else "")
            failing_tests, traceback_excerpt, summary = self._extract_concise_failure(combined_output, exit_code)

            return TestExecutionResult(
                command=cmd_display,
                exit_code=exit_code,
                passed=(exit_code == 0),
                duration_seconds=elapsed,
                concise_summary=summary,
                failing_tests=failing_tests,
                traceback_excerpt=traceback_excerpt,
                raw_output_truncated=combined_output[:self.max_log_chars],
                executed=True,
                timed_out=False,
                cancelled=False
            )

        except subprocess.TimeoutExpired:
            if process:
                kill_process_tree(process.pid)
                try:
                    process.kill()
                    process.communicate()
                except Exception:
                    pass
            self._active_process = None
            elapsed = time.time() - start_time
            return TestExecutionResult(
                command=cmd_display,
                exit_code=-1,
                passed=False,
                duration_seconds=elapsed,
                concise_summary=f"Test execution timed out after {timeout_sec:.1f}s",
                executed=True,
                timed_out=True,
                cancelled=False
            )
        except Exception as e:
            elapsed = time.time() - start_time
            return TestExecutionResult(
                command=cmd_display,
                exit_code=-2,
                passed=False,
                duration_seconds=elapsed,
                concise_summary=f"FAILED to execute test process: {e}",
                traceback_excerpt=str(e),
                executed=False,
                timed_out=False,
                cancelled=False
            )

    def _extract_concise_failure(self, output: str, exit_code: int) -> Tuple[List[str], str, str]:
        """Parse pytest/python output into concise diagnostic signals."""
        if exit_code == 0:
            # Tests passed
            passed_match = re.search(r"(\d+ passed)", output)
            passed_str = passed_match.group(1) if passed_match else "All tests passed"
            return [], "", f"PASS: {passed_str}"

        failing_tests = []
        # Find lines like: FAILED tests/test_foo.py::test_bar - AssertionError:...
        for line in output.splitlines():
            line_str = line.strip()
            if line_str.startswith("FAILED ") or " FAILED " in line_str:
                clean_name = line_str.replace("FAILED ", "").split(" - ")[0].strip()
                failing_tests.append(clean_name)

        # Extract traceback snippet (the failure assertion and relevant lines)
        traceback_lines = []
        capture = False
        for line in output.splitlines():
            if "=== FAILURES ===" in line or "___ " in line:
                capture = True
            elif "=== short test summary info ===" in line:
                capture = False
            elif capture:
                # Keep assertion markers and error lines
                if line.startswith("E   ") or line.startswith(">   ") or "AssertionError" in line:
                    traceback_lines.append(line.strip())

        # If empty, extract last 10 non-empty lines of output
        if not traceback_lines:
            non_empty = [l.strip() for l in output.splitlines() if l.strip()]
            traceback_lines = non_empty[-8:]

        traceback_str = "\n".join(traceback_lines[:12])  # Limit to 12 lines max
        summary = f"FAIL ({len(failing_tests)} test(s) failed)" if failing_tests else "FAIL (Test run exited with non-zero code)"
        return failing_tests, traceback_str, summary
