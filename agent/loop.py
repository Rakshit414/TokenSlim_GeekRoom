"""Autonomous coding execution loop.
Coordinates repository scanning, selective context retrieval, minimal patch application,
controlled test execution, iterative error repair, and early stopping.
"""
import os
import json
import time
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field

from agent.repository import RepositoryScanner, RepositoryMap
from agent.context import ContextRetriever, ContextPackage
from agent.edits import PatchEngine, PatchResult
from agent.verification import TestRunner, TestExecutionResult
from agent.bifrost_client import BifrostClient, BifrostUsage
from agent.prompts import SYSTEM_CODING_PROMPT, build_repair_prompt
from server.database import get_connection
from server.events import event_bus

class ExecutionSummary(BaseModel):
    run_id: str
    status: str
    iterations_count: int = 0
    tests_passed: bool = False
    baseline_test_passed: bool = False
    applied_patches_count: int = 0
    diffs: List[str] = Field(default_factory=list)
    total_tokens_spent: int = 0
    provider_reported_tokens: Optional[int] = None
    is_simulated: bool = False
    wall_clock_seconds: float = 0.0
    events_log: List[Dict[str, Any]] = Field(default_factory=list)
    final_message: str = ""

class AutonomousCodingLoop:
    def __init__(
        self,
        workspace_dir: str,
        task_directive: str,
        bifrost_client: Optional[BifrostClient] = None,
        test_command: Optional[str] = None,
        token_budget: int = 15000,
        max_repair_iterations: int = 4,
        time_limit_seconds: float = 120.0,
        run_id: Optional[str] = None,
        mock_patch_generator: Optional[Any] = None
    ):
        self.workspace_dir = Path(workspace_dir).resolve()
        self.task_directive = task_directive
        self.bifrost_client = bifrost_client or BifrostClient()
        self.test_command = test_command
        self.token_budget = token_budget
        self.max_repair_iterations = max_repair_iterations
        self.time_limit_seconds = time_limit_seconds
        self.run_id = run_id or f"run_{int(time.time())}"
        self.mock_patch_generator = mock_patch_generator

        self._cancelled = False
        self.events: List[Dict[str, Any]] = []

    def cancel(self):
        """Signal cancellation to abort active execution loop."""
        self._cancelled = True

    def _record_event(self, event_type: str, message: str, payload: Optional[Dict[str, Any]] = None):
        """Record and broadcast an execution telemetry event."""
        event = {
            "run_id": self.run_id,
            "type": event_type,
            "message": message,
            "data": payload or {},
            "timestamp": time.time()
        }
        self.events.append(event)

        # Broadcast via event bus if an event loop is currently running
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                asyncio.create_task(event_bus.broadcast(self.run_id, event))
        except RuntimeError:
            # No running event loop in current thread
            pass

        # Persist to database if table exists
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO run_events (run_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, datetime('now'))
            """, (self.run_id, event_type, json.dumps(event)))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def run(self) -> ExecutionSummary:
        """Execute the autonomous coding loop to completion or failure."""
        start_time = time.time()
        self._record_event("start", f"Initiating TokenSlim run for task: {self.task_directive[:80]}...")

        patch_engine = PatchEngine(str(self.workspace_dir))
        test_runner = TestRunner(str(self.workspace_dir))

        total_tokens = 0
        provider_reported_tokens_total: Optional[int] = None
        is_simulated = False
        applied_diffs: List[str] = []

        # 1. Baseline Test Run
        self._record_event("test_baseline", "Executing baseline tests to establish initial state...")
        baseline_res = test_runner.run_tests(test_command=self.test_command)
        baseline_passed = baseline_res.passed
        self._record_event("test_baseline_result", f"Baseline tests result: {baseline_res.concise_summary}", {
            "passed": baseline_passed,
            "failing_tests": baseline_res.failing_tests
        })

        if baseline_passed:
            # Code is already passing tests
            self._record_event("finish", "Baseline tests already pass. No repair required.")
            return ExecutionSummary(
                run_id=self.run_id,
                status="COMPLETED_VERIFIED",
                iterations_count=0,
                tests_passed=True,
                baseline_test_passed=True,
                total_tokens_spent=0,
                is_simulated=is_simulated,
                wall_clock_seconds=time.time() - start_time,
                events_log=self.events,
                final_message="Repository tests pass initially."
            )

        # 2. Repository Scan
        self._record_event("repo_scan", "Scanning repository structure with AST...")
        scanner = RepositoryScanner(str(self.workspace_dir))
        repo_map = scanner.scan()
        self._record_event("repo_scan_complete", f"Repository map ready: {repo_map.total_files} files, {repo_map.total_lines} lines.")

        # 3. Context Selection
        retriever = ContextRetriever(repo_map, max_tokens=min(4000, self.token_budget // 2))
        query_terms = self.task_directive
        if baseline_res.failing_tests:
            query_terms += " " + " ".join(baseline_res.failing_tests)

        context_pkg = retriever.retrieve(query_terms)
        self._record_event("context_selected", f"Retrieved {len(context_pkg.slices)} minimal slices from {context_pkg.metrics.retrieved_files_count} file(s). Estimated tokens: {context_pkg.metrics.estimated_tokens}", {
            "estimated_tokens": context_pkg.metrics.estimated_tokens,
            "slices_count": len(context_pkg.slices)
        })

        # 4. Iterative Repair Loop
        iteration = 0
        tests_passed = False
        last_failure_summary = baseline_res.concise_summary
        last_traceback = baseline_res.traceback_excerpt
        last_patch_error = ""

        while iteration < self.max_repair_iterations:
            iteration += 1
            elapsed = time.time() - start_time

            # Check termination limits
            if self._cancelled:
                self._record_event("cancelled", "Execution cancelled by user request.")
                return self._build_summary("CANCELLED", iteration, tests_passed, baseline_passed, applied_diffs, total_tokens, provider_reported_tokens_total, is_simulated, elapsed, "Run cancelled by user.")

            if elapsed > self.time_limit_seconds:
                self._record_event("timeout", f"Time limit exceeded ({elapsed:.1f}s > {self.time_limit_seconds:.1f}s).")
                return self._build_summary("TIMEOUT_EXCEEDED", iteration, tests_passed, baseline_passed, applied_diffs, total_tokens, provider_reported_tokens_total, is_simulated, elapsed, "Execution time limit exceeded.")

            if total_tokens >= self.token_budget:
                self._record_event("budget_exhausted", f"Token budget exhausted ({total_tokens} >= {self.token_budget}).")
                return self._build_summary("BUDGET_EXHAUSTED", iteration, tests_passed, baseline_passed, applied_diffs, total_tokens, provider_reported_tokens_total, is_simulated, elapsed, "Token budget exhausted.")

            self._record_event("iteration_start", f"Starting repair iteration {iteration}/{self.max_repair_iterations}...")

            # Generate minimal patch
            patch_text = ""
            if self.mock_patch_generator:
                patch_text = self.mock_patch_generator(iteration, last_failure_summary, last_patch_error)
                usage = BifrostUsage(
                    input_tokens=150,
                    output_tokens=50,
                    total_tokens=200,
                    model="mock-agent-adapter",
                    is_simulated=True,
                    provider="mock-adapter"
                )
                is_simulated = True
                total_tokens += usage.total_tokens
            else:
                prompt = build_repair_prompt(
                    task_directive=self.task_directive,
                    context_code=context_pkg.formatted_prompt_context,
                    failing_test_summary=last_failure_summary,
                    traceback_excerpt=last_traceback,
                    iteration=iteration,
                    patch_error=last_patch_error
                )

                messages = [
                    {"role": "system", "content": SYSTEM_CODING_PROMPT},
                    {"role": "user", "content": prompt}
                ]

                try:
                    patch_text, usage = self.bifrost_client.chat_completion(
                        messages=messages,
                        temperature=0.1
                    )
                    total_tokens += usage.total_tokens
                    if usage.is_simulated:
                        is_simulated = True
                    else:
                        if usage.provider_reported_total_tokens is not None:
                            provider_reported_tokens_total = (provider_reported_tokens_total or 0) + usage.provider_reported_total_tokens

                    self._record_event("model_call", f"Bifrost completion received. Spent {usage.total_tokens} tokens (Simulated: {usage.is_simulated}).", {
                        "model": usage.model,
                        "tokens": usage.total_tokens,
                        "is_simulated": usage.is_simulated
                    })
                except Exception as err:
                    self._record_event("model_error", f"Bifrost gateway error: {err}")
                    return self._build_summary("FAILED", iteration, tests_passed, baseline_passed, applied_diffs, total_tokens, provider_reported_tokens_total, is_simulated, elapsed, f"Model gateway failure: {err}")

            # Apply patch
            patch_results = patch_engine.apply_patch_text(patch_text)
            applied_any = False
            last_patch_error = ""

            for pres in patch_results:
                if pres.success:
                    applied_any = True
                    applied_diffs.append(pres.diff)
                    self._record_event("patch_applied", f"Successfully applied patch to {pres.file_path}", {
                        "file_path": pres.file_path,
                        "diff": pres.diff
                    })
                else:
                    last_patch_error = pres.error_message or "Patch failed to apply"
                    self._record_event("patch_rejected", f"Patch rejected: {last_patch_error}", {
                        "stale": pres.stale_detected,
                        "ambiguous": pres.ambiguous_detected
                    })

            if not applied_any:
                self._record_event("iteration_no_patch", f"No valid patches applied in iteration {iteration}. Retrying with error feedback.")
                continue

            # Run tests to verify the patch
            self._record_event("test_run", f"Running targeted tests to verify iteration {iteration} patch...")
            test_res = test_runner.run_tests(test_command=self.test_command)

            if test_res.passed:
                # Early Stopping immediately upon passing!
                tests_passed = True
                self._record_event("test_passed", f"Tests passed! {test_res.concise_summary}. Early stopping triggered.")
                break
            else:
                last_failure_summary = test_res.concise_summary
                last_traceback = test_res.traceback_excerpt
                self._record_event("test_failed", f"Tests failed after patch: {test_res.concise_summary}", {
                    "failing_tests": test_res.failing_tests
                })

        # 5. Final summary
        final_elapsed = time.time() - start_time
        status = "COMPLETED_VERIFIED" if tests_passed else "MAX_ITERATIONS_REACHED" if iteration >= self.max_repair_iterations else "FAILED"
        msg = "Task successfully solved and verified by tests." if tests_passed else f"Repair exhausted after {iteration} iteration(s) without passing tests."

        self._record_event("finish", f"Autonomous loop finished with status: {status}. {msg}")
        return self._build_summary(status, iteration, tests_passed, baseline_passed, applied_diffs, total_tokens, provider_reported_tokens_total, is_simulated, final_elapsed, msg)

    def _build_summary(
        self,
        status: str,
        iterations: int,
        passed: bool,
        baseline_passed: bool,
        diffs: List[str],
        tokens: int,
        provider_tokens: Optional[int],
        is_simulated: bool,
        elapsed: float,
        message: str
    ) -> ExecutionSummary:
        """Construct summary and update SQLite persistence."""
        summary = ExecutionSummary(
            run_id=self.run_id,
            status=status,
            iterations_count=iterations,
            tests_passed=passed,
            baseline_test_passed=baseline_passed,
            applied_patches_count=len(diffs),
            diffs=diffs,
            total_tokens_spent=tokens,
            provider_reported_tokens=provider_tokens,
            is_simulated=is_simulated,
            wall_clock_seconds=elapsed,
            events_log=self.events,
            final_message=message
        )

        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE runs
                SET status = ?, diff_text = ?, completed_at = datetime('now')
                WHERE run_id = ?
            """, (status, "\n".join(diffs), self.run_id))
            conn.commit()
            conn.close()
        except Exception:
            pass

        return summary
