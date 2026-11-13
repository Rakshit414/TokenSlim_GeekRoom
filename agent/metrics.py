"""Granular token accounting and model cost tracking for Bifrost gateway.
Maintains strict separation between provider-reported usage, local context estimates,
and simulated/mock usage. Calculates costs with auditable pricing catalog.
"""
import time
from typing import Dict, List, Optional, Tuple, Any
from pydantic import BaseModel, Field

class ModelPricing(BaseModel):
    model_name: str
    input_rate_per_million: float
    output_rate_per_million: float
    cached_input_rate_per_million: float
    pricing_source: str
    last_updated: str

# Configurable catalog with verified public rates per 1M tokens
MODEL_PRICING_CATALOG: Dict[str, ModelPricing] = {
    "gpt-4o-mini": ModelPricing(
        model_name="gpt-4o-mini",
        input_rate_per_million=0.15,
        output_rate_per_million=0.60,
        cached_input_rate_per_million=0.075,
        pricing_source="OpenAI Pricing Documentation",
        last_updated="2026-01-15"
    ),
    "gpt-4o": ModelPricing(
        model_name="gpt-4o",
        input_rate_per_million=2.50,
        output_rate_per_million=10.00,
        cached_input_rate_per_million=1.25,
        pricing_source="OpenAI Pricing Documentation",
        last_updated="2026-01-15"
    ),
    "claude-3-5-haiku-20241022": ModelPricing(
        model_name="claude-3-5-haiku-20241022",
        input_rate_per_million=0.80,
        output_rate_per_million=4.00,
        cached_input_rate_per_million=0.08,
        pricing_source="Anthropic Pricing Documentation",
        last_updated="2026-01-15"
    ),
    "claude-3-5-sonnet-20241022": ModelPricing(
        model_name="claude-3-5-sonnet-20241022",
        input_rate_per_million=3.00,
        output_rate_per_million=15.00,
        cached_input_rate_per_million=0.30,
        pricing_source="Anthropic Pricing Documentation",
        last_updated="2026-01-15"
    ),
    "gemini-1.5-flash": ModelPricing(
        model_name="gemini-1.5-flash",
        input_rate_per_million=0.075,
        output_rate_per_million=0.30,
        cached_input_rate_per_million=0.01875,
        pricing_source="Google Cloud AI Pricing Documentation",
        last_updated="2026-01-15"
    )
}

def calculate_call_cost(
    model: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    cached_tokens: Optional[int] = 0
) -> Tuple[Optional[float], Optional[str]]:
    """Calculate cost estimate based on known pricing rates.
    Returns (estimated_cost, explanation_note). Never fabricates costs for unknown models.
    """
    if input_tokens is None or output_tokens is None:
        return None, "Usage numbers unavailable from provider; cost uncalculable"

    # Match exact or normalized model prefix
    matched_pricing = None
    model_lower = model.lower()
    for key, p in MODEL_PRICING_CATALOG.items():
        if key.lower() == model_lower or model_lower.startswith(key.lower()):
            matched_pricing = p
            break

    if not matched_pricing:
        return None, f"Model '{model}' has no rate entry in pricing catalog; cost unavailable"

    cached_toks = cached_tokens or 0
    non_cached_input = max(0, input_tokens - cached_toks)

    input_cost = (non_cached_input / 1_000_000.0) * matched_pricing.input_rate_per_million
    cached_cost = (cached_toks / 1_000_000.0) * matched_pricing.cached_input_rate_per_million
    output_cost = (output_tokens / 1_000_000.0) * matched_pricing.output_rate_per_million

    total_est = round(input_cost + cached_cost + output_cost, 7)
    note = f"Calculated estimate using {matched_pricing.pricing_source} (updated {matched_pricing.last_updated})"
    return total_est, note

class ModelCallRecord(BaseModel):
    call_id: str
    run_id: str
    model: str
    provider: str
    request_id: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    latency_seconds: Optional[float] = None
    calculated_cost: Optional[float] = None
    cost_calculation_note: Optional[str] = None
    is_simulated: bool = False
    timestamp: str

class RunMetricsLedger(BaseModel):
    run_id: str
    model_calls: List[ModelCallRecord] = Field(default_factory=list)
    locally_estimated_context_tokens: int = 0

    def add_call(self, record: ModelCallRecord):
        self.model_calls.append(record)

    @property
    def provider_input_tokens(self) -> int:
        """Sum of real provider-reported input tokens only."""
        return sum(c.input_tokens for c in self.model_calls if not c.is_simulated and c.input_tokens is not None)

    @property
    def provider_output_tokens(self) -> int:
        """Sum of real provider-reported output tokens only."""
        return sum(c.output_tokens for c in self.model_calls if not c.is_simulated and c.output_tokens is not None)

    @property
    def provider_total_tokens(self) -> int:
        """Sum of real provider-reported total tokens only."""
        return sum(c.total_tokens for c in self.model_calls if not c.is_simulated and c.total_tokens is not None)

    @property
    def provider_cached_tokens(self) -> int:
        """Sum of real provider cached input tokens."""
        return sum(c.cached_input_tokens for c in self.model_calls if not c.is_simulated and c.cached_input_tokens is not None)

    @property
    def simulated_total_tokens(self) -> int:
        """Sum of simulated tokens, kept strictly separate from provider totals."""
        return sum(c.total_tokens for c in self.model_calls if c.is_simulated and c.total_tokens is not None)

    @property
    def total_cost(self) -> Optional[float]:
        """Total calculated cost for provider-reported usage."""
        real_calls = [c for c in self.model_calls if not c.is_simulated]
        if not real_calls:
            return None
        total = 0.0
        for c in real_calls:
            if c.calculated_cost is None:
                return None  # Uncalculable if any real call has missing cost
            total += c.calculated_cost
        return round(total, 8)

    @property
    def average_latency_seconds(self) -> Optional[float]:
        real_latencies = [c.latency_seconds for c in self.model_calls if not c.is_simulated and c.latency_seconds is not None]
        if not real_latencies:
            return None
        return round(sum(real_latencies) / len(real_latencies), 3)

    def to_summary_dict(self) -> Dict[str, Any]:
        """Structured export for telemetry and API responses."""
        return {
            "run_id": self.run_id,
            "total_calls_count": len(self.model_calls),
            "real_provider_calls_count": sum(1 for c in self.model_calls if not c.is_simulated),
            "simulated_calls_count": sum(1 for c in self.model_calls if c.is_simulated),
            "provider_reported_usage": {
                "input_tokens": self.provider_input_tokens,
                "output_tokens": self.provider_output_tokens,
                "total_tokens": self.provider_total_tokens,
                "cached_tokens": self.provider_cached_tokens
            },
            "locally_estimated_context_tokens": self.locally_estimated_context_tokens,
            "simulated_usage": {
                "total_tokens": self.simulated_total_tokens
            },
            "total_calculated_cost": self.total_cost,
            "average_latency_seconds": self.average_latency_seconds,
            "is_purely_simulated": all(c.is_simulated for c in self.model_calls) if self.model_calls else True
        }
