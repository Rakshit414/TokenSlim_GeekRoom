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
from agent.context import ContextRetriever, ContextPackage, estimate_tokens
from agent.edits import PatchEngine, PatchResult
from agent.verification import TestRunner, TestExecutionResult
from agent.bifrost_client import BifrostClient, BifrostUsage
from agent.prompts import SYSTEM_CODING_PROMPT, build_repair_prompt
from agent.metrics import RunMetricsLedger, ModelCallRecord
from server.database import get_connection, save_run_event, save_execution_trace
from server.events import event_bus

class ExecutionSummary(BaseModel):
    run_id: str
    status: str
    configuration: str = "leancode_tavily"
    iterations_count: int = 0
    tests_passed: bool = False
    baseline_test_passed: bool = False
    applied_patches_count: int = 0
    diffs: List[str] = Field(default_factory=list)
    total_tokens_spent: int = 0
    provider_reported_tokens: Optional[int] = None
    estimated_context_tokens: int = 0
    is_simulated: bool = False
    wall_clock_seconds: float = 0.0
    events_log: List[Dict[str, Any]] = Field(default_factory=list)
    final_message: str = ""
    ledger_summary: Dict[str, Any] = Field(default_factory=dict)
    stale_detections: List[Dict[str, Any]] = Field(default_factory=list)
    tavily_searches: int = 0

class AutonomousCodingLoop:
    def __init__(
        self,
        workspace_dir: str,
        task_directive: str,
        bifrost_client: Optional[BifrostClient] = None,
        test_command: Optional[str] = None,
        configuration: str = "leancode_tavily",
        token_budget: int = 15000,
        max_repair_iterations: int = 4,
        time_limit_seconds: float = 120.0,
        run_id: Optional[str] = None,
        mock_patch_generator: Optional[Any] = None,
        stale_detector: Optional[Any] = None
    ):
        self.workspace_dir = Path(workspace_dir).resolve()
        self.task_directive = task_directive
        self.bifrost_client = bifrost_client or BifrostClient()
        self.test_command = test_command
        self.configuration = configuration
        self.token_budget = token_budget
        self.max_repair_iterations = max_repair_iterations
        self.time_limit_seconds = time_limit_seconds
        self.run_id = run_id or f"run_{int(time.time())}"
        self.mock_patch_generator = mock_patch_generator
        self.stale_detector = stale_detector
        self.ledger = RunMetricsLedger(run_id=self.run_id)

        self.stale_detections: List[Dict[str, Any]] = []
        self.tavily_searches: int = 0
        self._cancelled = False
        self._test_runner: Optional[TestRunner] = None
        self.events: List[Dict[str, Any]] = []

    def cancel(self):
        """Signal cancellation to abort active execution loop and terminate running test processes."""
        self._cancelled = True
        if self._test_runner:
            self._test_runner.cancel_active()

    def _persist_model_call(self, record: ModelCallRecord):
        """Persist granular model call record to SQLite database."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO model_calls (
                    run_id, call_id, model, provider, request_id,
                    input_tokens, output_tokens, total_tokens, cached_tokens,
                    latency_seconds, calculated_cost, is_simulated, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                record.run_id, record.call_id, record.model, record.provider, record.request_id,
                record.input_tokens, record.output_tokens, record.total_tokens, record.cached_input_tokens,
                record.latency_seconds, record.calculated_cost, 1 if record.is_simulated else 0
            ))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _check_task_already_satisfied(self, repo_map: RepositoryMap, baseline_passed: bool) -> Tuple[bool, str]:
        """Check whether the requested task is already satisfied or if changes are required."""
        if not baseline_passed:
            return False, "Baseline tests failed. Repair required."

        # Parse requested function or class names from task directive
        # Common patterns: "add function foo", "implement bar", "create class Baz", "def foo"
        import re
        tokens = re.findall(r"(?:function|def|class|method|implement|add)\s+([A-Za-z_][A-Za-z0-9_]*)", self.task_directive, re.IGNORECASE)
        
        for sym in tokens:
            sym_clean = sym.strip()
            if sym_clean.lower() in ("a", "an", "the", "new", "method", "function", "class", "feature"):
                continue
            matches = repo_map.find_symbol(sym_clean)
            if not matches:
                return False, f"Existing tests pass, but requested symbol '{sym_clean}' is not present in repository. Proceeding with implementation."

        # Also check if directive mentions "add" or "implement" or "feature" without specific keyword
        if re.search(r"\b(add|implement|create|new|feature|extend)\b", self.task_directive, re.IGNORECASE):
            # Check if there is an explicit request for something not yet present
            # Default to continuing implementation unless we have positive proof of satisfaction
            words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", self.task_directive)
            missing_targets = []
            for w in words:
                if w.lower() in ("add", "implement", "create", "function", "class", "feature", "code", "repo", "test", "tests"):
                    continue
                # If word looks like a python identifier and not found in any file
                if not repo_map.find_symbol(w) and not any(w.lower() in p.lower() for p in repo_map.files):
                    missing_targets.append(w)
            if missing_targets and len(missing_targets) <= 3:
                return False, f"Existing tests pass, but requested target(s) {missing_targets} are missing. Continuing implementation."

        return True, "All requested symbols exist and existing tests pass."

    def _record_event(self, event_type: str, message: str, payload: Optional[Dict[str, Any]] = None):
        """Record and broadcast an execution telemetry event with persistent sequential ID."""
        event = {
            "run_id": self.run_id,
            "type": event_type,
            "message": message,
            "data": payload or {},
            "timestamp": time.time()
        }

        # Persist to database to obtain deterministic sequential row ID
        try:
            event_id = save_run_event(self.run_id, event_type, event)
            event["id"] = event_id
        except Exception:
            event["id"] = len(self.events) + 1

        self.events.append(event)

        # Broadcast via event bus if an event loop is currently running
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                asyncio.create_task(event_bus.broadcast(self.run_id, event))
        except RuntimeError:
            # No running event loop in current thread
            pass

    def run(self) -> ExecutionSummary:
        """Execute the autonomous coding loop to completion or failure."""
        start_time = time.time()
        self._record_event("start", f"Initiating TokenSlim run for task: {self.task_directive[:80]}...")

        patch_engine = PatchEngine(str(self.workspace_dir))
        test_runner = TestRunner(str(self.workspace_dir))
        self._test_runner = test_runner

        total_tokens = 0
        provider_reported_tokens_total: Optional[int] = None
        is_simulated = False
        applied_diffs: List[str] = []

        # 1. Repository Scan
        self._record_event("repo_scan", "Scanning repository structure with AST...")
        scanner = RepositoryScanner(str(self.workspace_dir))
        repo_map = scanner.scan()
        self._record_event("repo_scan_complete", f"Repository map ready: {repo_map.total_files} files, {repo_map.total_lines} lines.")

        # 2. Baseline Test Run
        self._record_event("test_baseline", "Executing baseline tests to establish initial state...")
        baseline_res = test_runner.run_tests(test_command=self.test_command)
        baseline_passed = baseline_res.passed
        self._record_event("test_baseline_result", f"Baseline tests result: {baseline_res.concise_summary}", {
            "passed": baseline_passed,
            "failing_tests": baseline_res.failing_tests
        })

        # Check whether task is already satisfied
        task_satisfied, satisfaction_reason = self._check_task_already_satisfied(repo_map, baseline_passed)
        if task_satisfied:
            self._record_event("finish", f"Task verified: {satisfaction_reason}")
            return ExecutionSummary(
                run_id=self.run_id,
                status="COMPLETED_VERIFIED",
                configuration=self.configuration,
                iterations_count=0,
                tests_passed=True,
                baseline_test_passed=True,
                total_tokens_spent=0,
                is_simulated=is_simulated,
                wall_clock_seconds=time.time() - start_time,
                events_log=self.events,
                final_message=satisfaction_reason
            )
        elif baseline_passed:
            self._record_event("task_unfulfilled", f"{satisfaction_reason}")

        # 3. Context Selection & Stale-Answer Detection
        stale_guidance = None
        if self.configuration == "leancode_tavily":
            self._record_event("stale_detection_start", "Extracting technical assumptions and verifying with Tavily...")
            if not self.stale_detector:
                from agent.stale_detector import StaleAnswerDetector
                self.stale_detector = StaleAnswerDetector()

            code_snippets = {}
            for fpath in repo_map.files.keys():
                full_p = self.workspace_dir / fpath
                if full_p.exists() and full_p.is_file() and full_p.suffix in (".py", ".json", ".yaml", ".yml", ".toml"):
                    try:
                        code_snippets[fpath] = full_p.read_text(encoding="utf-8")
                    except Exception:
                        pass

            detection_run = self.stale_detector.run_detection(
                task=self.task_directive,
                code_snippets=code_snippets,
                max_searches=5,
                persist=True
            )
            self.tavily_searches = detection_run.searches_executed
            self.stale_detections = [c.model_dump() for c in detection_run.claims]
            if detection_run.is_simulated:
                is_simulated = True

            guidance_lines = []
            stale_claims = detection_run.stale_claims
            current_claims = detection_run.current_claims
            uncertain_claims = detection_run.uncertain_claims

            if stale_claims:
                guidance_lines.append("The following technical assumptions were confirmed STALE/DEPRECATED by official documentation:")
                for sc in stale_claims:
                    guidance_lines.append(f"- Outdated: {sc.claim_text}")
                    if sc.recommended_correction:
                        guidance_lines.append(f"  Correction: {sc.recommended_correction}")
                    if sc.suggested_patch:
                        guidance_lines.append(f"  Suggested Patch:\n{sc.suggested_patch}")
                    guidance_lines.append(f"  Evidence: {sc.reasoning}")

            if current_claims:
                guidance_lines.append("The following technical items were verified CURRENT; do NOT rewrite them unnecessarily:")
                for cc in current_claims:
                    guidance_lines.append(f"- Current: {cc.claim_text}")

            if uncertain_claims:
                guidance_lines.append("The following items had INSUFFICIENT documentation evidence (UNCERTAIN); preserve existing code unless failing tests directly prove an error:")
                for uc in uncertain_claims:
                    guidance_lines.append(f"- Uncertain: {uc.claim_text}")

            if guidance_lines:
                stale_guidance = "\n".join(guidance_lines)

            self._record_event("stale_detection_complete", f"Stale detector checked {len(detection_run.claims)} claim(s): {len(stale_claims)} STALE, {len(current_claims)} CURRENT, {len(uncertain_claims)} UNCERTAIN.", {
                "stale_count": len(stale_claims),
                "current_count": len(current_claims),
                "uncertain_count": len(uncertain_claims),
                "searches_executed": detection_run.searches_executed
            })

        # Context Selection: Broad for naive baseline vs AST Selective for LeanCode
        if self.configuration == "naive_baseline":
            broad_parts = []
            for p in sorted(self.workspace_dir.rglob("*")):
                if p.is_file() and not p.name.startswith(".") and "__pycache__" not in p.parts:
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        rel_path = str(p.relative_to(self.workspace_dir)).replace("\\", "/")
                        broad_parts.append(f"### File: {rel_path} (Full File Content)\n```\n{content}\n```")
                    except Exception:
                        pass
            if baseline_res.raw_output_truncated:
                broad_parts.append(f"### Unfiltered Raw Test Logs\n```\n{baseline_res.raw_output_truncated}\n```")
            formatted_context = "\n\n".join(broad_parts)
            self.ledger.locally_estimated_context_tokens = estimate_tokens(formatted_context)[0]
            self._record_event("context_selected", f"Naive baseline: Broad full-file context retrieved ({len(broad_parts)} sections). Estimated tokens: {self.ledger.locally_estimated_context_tokens}", {
                "estimated_tokens": self.ledger.locally_estimated_context_tokens,
                "mode": "naive_baseline"
            })
        else:
            retriever = ContextRetriever(repo_map, max_tokens=min(4000, self.token_budget // 2))
            query_terms = self.task_directive
            if baseline_res.failing_tests:
                query_terms += " " + " ".join(baseline_res.failing_tests)
            context_pkg = retriever.retrieve(query_terms)
            formatted_context = context_pkg.formatted_prompt_context
            self.ledger.locally_estimated_context_tokens = estimate_tokens(formatted_context)[0]
            self._record_event("context_selected", f"Retrieved {len(context_pkg.slices)} minimal slices from {context_pkg.metrics.retrieved_files_count} file(s). Estimated tokens: {self.ledger.locally_estimated_context_tokens}", {
                "estimated_tokens": self.ledger.locally_estimated_context_tokens,
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
                ctx_toks = self.ledger.locally_estimated_context_tokens or 200
                usage = BifrostUsage(
                    input_tokens=ctx_toks + 50,
                    output_tokens=50,
                    total_tokens=ctx_toks + 100,
                    request_id=f"mock_req_{iteration}",
                    model="mock-agent-adapter",
                    is_simulated=True,
                    provider="mock-adapter"
                )
                is_simulated = True
                total_tokens += usage.total_tokens

                call_record = ModelCallRecord(
                    call_id=f"call_{iteration}_{os.urandom(2).hex()}",
                    run_id=self.run_id,
                    model=usage.model,
                    provider=usage.provider or "mock-adapter",
                    request_id=usage.request_id,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                    cached_input_tokens=None,
                    latency_seconds=None,
                    calculated_cost=None,
                    cost_calculation_note="Cost unavailable for mock simulation",
                    is_simulated=True,
                    timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
                )
                self.ledger.add_call(call_record)
                self._persist_model_call(call_record)
            else:
                prompt = build_repair_prompt(
                    task_directive=self.task_directive,
                    context_code=formatted_context,
                    failing_test_summary=last_failure_summary,
                    traceback_excerpt=last_traceback,
                    iteration=iteration,
                    patch_error=last_patch_error,
                    stale_guidance=stale_guidance
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

                    call_record = ModelCallRecord(
                        call_id=f"call_{iteration}_{os.urandom(2).hex()}",
                        run_id=self.run_id,
                        model=usage.model,
                        provider=usage.provider or "bifrost",
                        request_id=usage.request_id,
                        input_tokens=usage.provider_reported_input_tokens if not usage.is_simulated else usage.input_tokens,
                        output_tokens=usage.provider_reported_output_tokens if not usage.is_simulated else usage.output_tokens,
                        total_tokens=usage.provider_reported_total_tokens if not usage.is_simulated else usage.total_tokens,
                        cached_input_tokens=usage.cached_tokens,
                        latency_seconds=usage.latency_seconds,
                        calculated_cost=usage.estimated_cost,
                        cost_calculation_note=usage.cost_calculation_note,
                        is_simulated=usage.is_simulated,
                        timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
                    )
                    self.ledger.add_call(call_record)
                    self._persist_model_call(call_record)

                    self._record_event("model_call", f"Bifrost completion received. Spent {usage.total_tokens} tokens (Simulated: {usage.is_simulated}, Model: {usage.model}, ReqID: {usage.request_id}).", {
                        "model": usage.model,
                        "tokens": usage.total_tokens,
                        "is_simulated": usage.is_simulated,
                        "request_id": usage.request_id,
                        "estimated_cost": usage.estimated_cost
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
            configuration=self.configuration,
            iterations_count=iterations,
            tests_passed=passed,
            baseline_test_passed=baseline_passed,
            applied_patches_count=len(diffs),
            diffs=diffs,
            total_tokens_spent=tokens,
            provider_reported_tokens=provider_tokens,
            estimated_context_tokens=self.ledger.locally_estimated_context_tokens,
            is_simulated=is_simulated,
            wall_clock_seconds=elapsed,
            events_log=self.events,
            final_message=message,
            ledger_summary=self.ledger.to_summary_dict(),
            stale_detections=self.stale_detections,
            tavily_searches=self.tavily_searches
        )

        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO runs (run_id, status, configuration, repo_path, prompt, metrics_json, stale_detections_json, diff_text, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    configuration = excluded.configuration,
                    metrics_json = excluded.metrics_json,
                    stale_detections_json = excluded.stale_detections_json,
                    diff_text = excluded.diff_text,
                    completed_at = datetime('now')
            """, (self.run_id, status, self.configuration, str(self.workspace_dir), self.task_directive, json.dumps(self.ledger.to_summary_dict()), json.dumps(self.stale_detections), "\n".join(diffs)))
            conn.commit()
            conn.close()
        except Exception:
            pass

        try:
            save_execution_trace(self.run_id, summary.model_dump())
        except Exception:
            pass

        return summary
