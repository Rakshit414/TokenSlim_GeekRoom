"""Pydantic data schemas for TokenSlim server API."""
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from datetime import datetime

class RunCreateRequest(BaseModel):
    repo_path: str = Field(..., description="Target repository path or preset name")
    configuration: Literal["naive_baseline", "leancode", "leancode_tavily"] = Field(
        default="leancode_tavily",
        description="Coding agent benchmark configuration"
    )
    prompt: Optional[str] = Field(default="", description="Specific task directive or issue description")
    token_budget: Optional[int] = Field(default=15000, description="Maximum total token budget")
    replay: bool = Field(default=False, description="Replay pre-recorded execution trace if available")

class StaleDetectionRecord(BaseModel):
    id: str
    claim: str
    library: Optional[str] = None
    version_context: Optional[str] = None
    trigger: str
    classification: Literal["CURRENT", "STALE", "UNCERTAIN"]
    evidence: str
    source_title: Optional[str] = None
    source_url: Optional[str] = None
    date_checked: str
    confidence: str
    recommended_correction: Optional[str] = None
    verification_passed: Optional[bool] = None

class TokenMetrics(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    estimated_cost: Optional[float] = None
    duration_seconds: float = 0.0
    repair_iterations: int = 0
    tavily_searches: int = 0
    stale_detections_count: int = 0

class RunResponse(BaseModel):
    run_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    configuration: str
    repo_path: str
    metrics: TokenMetrics
    stale_detections: List[StaleDetectionRecord] = []
    created_at: datetime
    completed_at: Optional[datetime] = None

class HealthResponse(BaseModel):
    status: str
    version: str
    bifrost: Dict[str, Any]
    tavily: Dict[str, Any]
    database: Dict[str, Any]
    environment: str
