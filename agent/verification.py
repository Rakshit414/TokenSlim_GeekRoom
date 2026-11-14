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

# Permitted test execution binaries
ALLOWED_EXECUTABLE_NAMES = {
    "python", "python3", "python.exe", "pytest", "pytest.exe", "py.test"
}

DISALLOWED_SHELL_OPERATORS = {
    "&&", "||", ";", "|", "&", ">", "<", "`", "$", "\n", "\r"
}

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

    def _validate_and_sanitize_command(
        self,
        test_command: Optional[str],
        target_file: Optional[str]
    ) -> Tuple[List[str], Optional[str]]:
        """Validate test command against security rules, path escapes, and prohibited executables.
        Returns: (sanitized_argv_list, error_message)
        """
        if not test_command:
            if target_file:
                tf_path = Path(target_file)
                if not tf_path.is_absolute():
                    tf_path = (self.workspace_dir / tf_path).resolve()
                else:
                    tf_path = tf_path.resolve()
                try:
                    if not tf_path.is_relative_to(self.workspace_dir):
                        return [], f"Security violation: Target file '{target_file}' escapes workspace boundary."
                except AttributeError:
                    if not str(tf_path).startswith(str(self.workspace_dir)):
                        return [], f"Security violation: Target file '{target_file}' escapes workspace boundary."
                if not tf_path.exists():
                    return [], f"Target test file does not exist: {target_file}"
                return [self.python_executable, "-m", "pytest", "-v", str(tf_path)], None
            else:
                return [self.python_executable, "-m", "pytest", "-v"], None

        # Check for shell operators (pipes, chaining, redirection)
        for op in DISALLOWED_SHELL_OPERATORS:
            if op in test_command:
                return [], f"Security violation: Disallowed shell operator '{op}' detected in test command."

        import shlex
        try:
            tokens = shlex.split(test_command, posix=(sys.platform != "win32"))
            tokens = [t.strip('"\'') for t in tokens]
        except Exception as e:
            return [], f"Security violation: Malformed test command cannot be parsed: {e}"

        if not tokens:
            return [], "Test command cannot be empty."

        # Validate executable
        exe_token = tokens[0]
        exe_path = Path(exe_token)
        exe_name = exe_path.name.lower()

        # Check against allowed executables
        is_allowed_name = exe_name in ALLOWED_EXECUTABLE_NAMES
        is_python_exec = False
        try:
            is_python_exec = (exe_path.resolve() == Path(self.python_executable).resolve() or
                              exe_path.resolve() == Path(sys.executable).resolve())
        except Exception:
            pass

        if not is_allowed_name and not is_python_exec:
            return [], f"Security violation: Executable '{exe_token}' is not in the permitted test runners allowlist."

        # Check arguments for path escapes or sensitive directory access
        for arg in tokens[1:]:
            if "/" in arg or "\\" in arg or arg.endswith(".py"):
                clean_arg = arg.split("=")[-1] if "=" in arg else arg
                p_arg = Path(clean_arg)
                if p_arg.is_absolute():
                    try:
                        if not p_arg.resolve().is_relative_to(self.workspace_dir):
                            return [], f"Security violation: Argument '{arg}' accesses path outside workspace boundary."
                    except AttributeError:
                        if not str(p_arg.resolve()).startswith(str(self.workspace_dir)):
                            return [], f"Security violation: Argument '{arg}' accesses path outside workspace boundary."
                elif ".." in p_arg.parts:
                    resolved = (self.workspace_dir / p_arg).resolve()
                    try:
                        if not resolved.is_relative_to(self.workspace_dir):
                            return [], f"Security violation: Argument '{arg}' escapes workspace boundary via parent traversal."
                    except AttributeError:
                        if not str(resolved).startswith(str(self.workspace_dir)):
                            return [], f"Security violation: Argument '{arg}' escapes workspace boundary via parent traversal."

        return tokens, None

    def run_tests(
        self,
        test_command: Optional[str] = None,
        target_file: Optional[str] = None,
        timeout: Optional[float] = None
    ) -> TestExecutionResult:
        """Execute tests in workspace and return concise, actionable results."""
        timeout_sec = timeout or self.default_timeout_seconds

        # Validate and sanitize command against security rules
        cmd, sec_error = self._validate_and_sanitize_command(test_command, target_file)
        cmd_display = " ".join(cmd) if cmd else (test_command or target_file or "pytest")

        if sec_error:
            return TestExecutionResult(
                command=cmd_display,
                exit_code=-2,
                passed=False,
                duration_seconds=0.0,
                concise_summary=f"FAILED to execute test process: {sec_error}",
                traceback_excerpt=sec_error,
                executed=False,
                timed_out=False,
                cancelled=False
            )

        start_time = time.time()
        self._active_process = None

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
            # Run in workspace directory with isolated, secret-stripped environment
            env = os.environ.copy()
            for secret_key in (
                "TAVILY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                "BIFROST_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN"
            ):
                env.pop(secret_key, None)
            # Ensure workspace is at front of PYTHONPATH
            env["PYTHONPATH"] = str(self.workspace_dir) + os.pathsep + env.get("PYTHONPATH", "")

            process = subprocess.Popen(
                cmd,
                shell=False,
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
