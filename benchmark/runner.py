"""TokenSlim Benchmark Runner.
Executes the reproducible three-way benchmark (Naive Baseline vs LeanCode vs LeanCode + Tavily)
across the 12 benchmark tasks in isolated workspaces with comprehensive token and correctness accounting.
"""
import os
import sys
import json
import time
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.loop import AutonomousCodingLoop, ExecutionSummary
from agent.bifrost_client import BifrostClient
from agent.stale_detector import StaleAnswerDetector

BENCHMARK_DIR = Path(__file__).resolve().parent
TASKS_DIR = BENCHMARK_DIR / "tasks"
RESULTS_FILE = BENCHMARK_DIR / "results.json"

class TaskBenchmarkRunResult(BaseModel):
    task_id: str
    configuration: str  # naive_baseline | leancode | leancode_tavily
    model: str
    status: str
    passed: bool
    baseline_passed: bool
    iterations_count: int
    wall_clock_seconds: float
    # Explicit separation of simulated vs estimated vs provider tokens:
    is_simulated: bool = False
    simulated_tokens_total: int = 0
    locally_estimated_context_tokens: int = 0
    provider_reported_input_tokens: Optional[int] = None
    provider_reported_output_tokens: Optional[int] = None
    provider_reported_total_tokens: Optional[int] = None
    # Retained for backward compatibility
    total_tokens_spent: int = 0
    estimated_context_tokens: int = 0
    provider_reported_tokens: Optional[int] = None
    tavily_searches_count: int = 0
    stale_detections_count: int = 0
    calculated_cost: Optional[float] = None
    error_message: Optional[str] = None

class BenchmarkSuiteSummary(BaseModel):
    run_timestamp: str
    tasks_count: int
    model_name: str
    is_simulated: bool
    configurations: Dict[str, Dict[str, Any]]
    task_results: List[TaskBenchmarkRunResult]

# Deterministic task-specific mock patch generators for offline benchmark testing
TASK_CORRECT_PATCHES = {
    "task_01_factorial_off_by_one": """FILE: calculator.py
<<<<<<< SEARCH
    for i in range(1, n):
        result *= i
=======
    for i in range(1, n + 1):
        result *= i
>>>>>>> REPLACE""",

    "task_02_invoice_selective_context": """FILE: invoice_service.py
<<<<<<< SEARCH
def format_invoice_id(invoice_num: int) -> str:
    \"\"\"Format numeric invoice ID with standard prefix and zero padding.\"\"\"
    # Bug: missing INV- prefix and zero padding
    return f"{invoice_num}"
=======
def format_invoice_id(invoice_num: int) -> str:
    \"\"\"Format numeric invoice ID with standard prefix and zero padding.\"\"\"
    return f"INV-{invoice_num:05d}"
>>>>>>> REPLACE""",

    "task_03_pydantic_v2_dict_deprecation": """FILE: models.py
<<<<<<< SEARCH
def serialize_user(user: UserProfile) -> dict:
    # Stale/deprecated API usage in Pydantic v2
    return user.dict()
=======
def serialize_user(user: UserProfile) -> dict:
    return user.model_dump()
>>>>>>> REPLACE""",

    "task_04_pydantic_v2_parse_obj": """FILE: loader.py
<<<<<<< SEARCH
def load_config(raw_dict: dict) -> AppConfig:
    # Stale/deprecated in Pydantic v2
    return AppConfig.parse_obj(raw_dict)
=======
def load_config(raw_dict: dict) -> AppConfig:
    return AppConfig.model_validate(raw_dict)
>>>>>>> REPLACE""",

    "task_05_datetime_utcnow_deprecation": """FILE: session.py
<<<<<<< SEARCH
        created_at = datetime.utcnow()
=======
        created_at = datetime.now(timezone.utc)
>>>>>>> REPLACE""",

    "task_06_openai_sdk_v1_chat_completion": """FILE: llm_gateway.py
<<<<<<< SEARCH
def query_model(prompt: str, model: str = "gpt-4o-mini") -> str:
    # Removed global method in OpenAI SDK v1.0+
    response = openai.ChatCompletion.create(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content
=======
def query_model(prompt: str, model: str = "gpt-4o-mini") -> str:
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content
>>>>>>> REPLACE""",

    "task_07_collections_abc_mapping": """FILE: mapping_utils.py
<<<<<<< SEARCH
from collections import Mapping
=======
from collections.abc import Mapping
>>>>>>> REPLACE""",

    "task_08_current_api_preserved": """FILE: api_handler.py
<<<<<<< SEARCH
    return {
        "status_code": 200,
        "item": item.model_dump()
    }
=======
    return {
        "status_code": 201,
        "item": item.model_dump()
    }
>>>>>>> REPLACE""",

    "task_09_uncertain_obscure_math": """FILE: math_internal.py
<<<<<<< SEARCH
    if exp == 0:
        return 0
=======
    if exp == 0:
        return 1
>>>>>>> REPLACE""",

    "task_10_deprecated_model_param": """FILE: settings.py
<<<<<<< SEARCH
DEFAULT_MODEL = "text-davinci-003"
=======
DEFAULT_MODEL = "gpt-4o-mini"
>>>>>>> REPLACE""",

    "task_11_string_reversal_edge_cases": """FILE: text_cleaner.py
<<<<<<< SEARCH
    words = text.split(" ")
    return " ".join(reversed(words))
=======
    words = text.split()
    return " ".join(reversed(words))
>>>>>>> REPLACE""",

    "task_12_pkg_resources_migration": """FILE: asset_reader.py
<<<<<<< SEARCH
# Stale: pkg_resources is deprecated
import pkg_resources

def read_package_asset(package_name: str, asset_filename: str) -> str:
    # Stale API
    return pkg_resources.resource_string(package_name, asset_filename).decode("utf-8")
=======
import importlib.resources

def read_package_asset(package_name: str, asset_filename: str) -> str:
    return importlib.resources.files(package_name).joinpath(asset_filename).read_text(encoding="utf-8")
>>>>>>> REPLACE"""
}

class BenchmarkRunner:
    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        bifrost_client: Optional[BifrostClient] = None,
        stale_detector: Optional[StaleAnswerDetector] = None,
        use_deterministic_mocks: bool = True
    ):
        self.model_name = model_name
        self.bifrost_client = bifrost_client or BifrostClient()
        self.stale_detector = stale_detector or StaleAnswerDetector()
        self.use_deterministic_mocks = use_deterministic_mocks

    def run_task(
        self,
        task_id: str,
        configuration: str
    ) -> TaskBenchmarkRunResult:
        """Run a single task under a specific configuration in an isolated temporary clone."""
        task_src_dir = TASKS_DIR / task_id
        if not task_src_dir.exists():
            raise FileNotFoundError(f"Task directory {task_src_dir} does not exist.")

        task_meta = json.loads((task_src_dir / "task.json").read_text(encoding="utf-8"))

        # Create isolated workspace copy
        temp_dir = tempfile.mkdtemp(prefix=f"bench_{task_id}_{configuration}_")
        try:
            for item in task_src_dir.iterdir():
                if item.name != "task.json":
                    if item.is_file():
                        shutil.copy2(item, Path(temp_dir) / item.name)
                    elif item.is_dir():
                        shutil.copytree(item, Path(temp_dir) / item.name)

            # Deterministic mock patch generator when running without live gateway
            mock_gen = None
            if self.use_deterministic_mocks:
                correct_patch = TASK_CORRECT_PATCHES.get(task_id, "")
                def _gen(iteration, failure, patch_err):
                    # For naive_baseline, generate on iteration 1
                    # For leancode, generate minimal patch
                    # For leancode_tavily, generate with evidence guidance
                    return correct_patch
                mock_gen = _gen

            loop = AutonomousCodingLoop(
                workspace_dir=temp_dir,
                task_directive=task_meta["description"],
                bifrost_client=self.bifrost_client,
                configuration=configuration,
                stale_detector=self.stale_detector,
                mock_patch_generator=mock_gen,
                token_budget=15000,
                max_repair_iterations=3,
                time_limit_seconds=60.0
            )

            summary = loop.run()

            # Record task benchmark result with strict separation of simulated vs real metrics
            is_sim = summary.is_simulated or self.use_deterministic_mocks
            sim_tokens = summary.total_tokens_spent if is_sim else 0
            prov_input = summary.ledger_summary.get("provider_reported_input_tokens") if not is_sim else None
            prov_output = summary.ledger_summary.get("provider_reported_output_tokens") if not is_sim else None
            prov_total = summary.provider_reported_tokens if not is_sim else None

            return TaskBenchmarkRunResult(
                task_id=task_id,
                configuration=configuration,
                model=self.model_name,
                status=summary.status,
                passed=summary.tests_passed,
                baseline_passed=summary.baseline_test_passed,
                iterations_count=summary.iterations_count,
                wall_clock_seconds=round(summary.wall_clock_seconds, 3),
                is_simulated=is_sim,
                simulated_tokens_total=sim_tokens,
                locally_estimated_context_tokens=summary.estimated_context_tokens,
                provider_reported_input_tokens=prov_input,
                provider_reported_output_tokens=prov_output,
                provider_reported_total_tokens=prov_total,
                total_tokens_spent=summary.total_tokens_spent,
                estimated_context_tokens=summary.estimated_context_tokens,
                provider_reported_tokens=prov_total,
                tavily_searches_count=summary.tavily_searches,
                stale_detections_count=len(summary.stale_detections),
                calculated_cost=summary.ledger_summary.get("total_cost")
            )

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def run_all(self, task_ids: Optional[List[str]] = None) -> BenchmarkSuiteSummary:
        """Execute the complete 3-way benchmark across all tasks."""
        if not task_ids:
            task_ids = [t.name for t in TASKS_DIR.iterdir() if t.is_dir() and (t / "task.json").exists()]
            task_ids.sort()

        results: List[TaskBenchmarkRunResult] = []
        configurations = ["naive_baseline", "leancode", "leancode_tavily"]

        print(f"Starting 3-way benchmark across {len(task_ids)} tasks on model '{self.model_name}'...")

        for tid in task_ids:
            for cfg in configurations:
                res = self.run_task(tid, cfg)
                results.append(res)
                print(f"[{cfg:15}] Task {tid:35} -> {'PASSED' if res.passed else 'FAILED'} (Simulated: {res.simulated_tokens_total}, Context: {res.locally_estimated_context_tokens})")

        # Compute summary metrics for each configuration
        config_metrics: Dict[str, Dict[str, Any]] = {}
        for cfg in configurations:
            cfg_res = [r for r in results if r.configuration == cfg]
            total_tasks = len(cfg_res)
            passed_tasks = sum(1 for r in cfg_res if r.passed)
            pass_rate = round((passed_tasks / total_tasks * 100.0) if total_tasks else 0.0, 1)
            total_simulated = sum(r.simulated_tokens_total for r in cfg_res)
            total_provider = sum(r.provider_reported_total_tokens or 0 for r in cfg_res) if any(r.provider_reported_total_tokens is not None for r in cfg_res) else None
            total_context = sum(r.locally_estimated_context_tokens for r in cfg_res)
            avg_duration = round(sum(r.wall_clock_seconds for r in cfg_res) / total_tasks, 2) if total_tasks else 0.0
            avg_iterations = round(sum(r.iterations_count for r in cfg_res) / total_tasks, 2) if total_tasks else 0.0
            tavily_searches = sum(r.tavily_searches_count for r in cfg_res)
            stale_detections = sum(r.stale_detections_count for r in cfg_res)

            config_metrics[cfg] = {
                "tasks_total": total_tasks,
                "tasks_passed": passed_tasks,
                "pass_rate_pct": pass_rate,
                "is_simulated": self.use_deterministic_mocks,
                "total_simulated_tokens": total_simulated,
                "total_provider_reported_tokens": total_provider,
                "total_context_tokens": total_context,
                "total_tokens_spent": total_simulated,  # Legacy alias
                "average_iterations": avg_iterations,
                "average_duration_seconds": avg_duration,
                "tavily_searches": tavily_searches,
                "stale_detections": stale_detections
            }

        # Calculate comparative reduction percentages
        naive_context = config_metrics["naive_baseline"]["total_context_tokens"] or 1

        leancode_context = config_metrics["leancode"]["total_context_tokens"]
        leancode_tavily_context = config_metrics["leancode_tavily"]["total_context_tokens"]

        config_metrics["leancode"]["context_reduction_pct"] = round(
            max(0.0, (naive_context - leancode_context) / naive_context * 100.0), 1
        )
        config_metrics["leancode_tavily"]["context_reduction_pct"] = round(
            max(0.0, (naive_context - leancode_tavily_context) / naive_context * 100.0), 1
        )

        suite_summary = BenchmarkSuiteSummary(
            run_timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            tasks_count=len(task_ids),
            model_name=self.model_name,
            is_simulated=self.use_deterministic_mocks,
            configurations=config_metrics,
            task_results=results
        )

        # Save results to benchmark/results.json
        RESULTS_FILE.write_text(suite_summary.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nBenchmark suite complete. Results saved to {RESULTS_FILE}")
        return suite_summary

if __name__ == "__main__":
    runner = BenchmarkRunner()
    runner.run_all()
