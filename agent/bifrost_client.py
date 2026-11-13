"""Bifrost LLM Gateway client integration.
Directs all model requests through Bifrost gateway (Bifrost Problem Statement #01).
Extracts precise token metrics, latency, model information, and request telemetry.
"""
import os
import time
from typing import Dict, Any, List, Optional, Tuple
from openai import OpenAI, APIConnectionError, AuthenticationError
from pydantic import BaseModel

class BifrostUsage(BaseModel):
    # Provider-reported tokens (None if simulated / offline)
    provider_reported_input_tokens: Optional[int] = None
    provider_reported_output_tokens: Optional[int] = None
    provider_reported_total_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    
    # Token counts for tracking (explicitly labeled if simulated)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    
    request_id: Optional[str] = None
    model: str = ""
    latency_seconds: Optional[float] = None
    estimated_cost: Optional[float] = None
    cost_calculation_note: Optional[str] = None
    gateway_connected: bool = True
    provider: Optional[str] = "bifrost"
    is_simulated: bool = False
    simulation_note: Optional[str] = None

class BifrostClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        timeout: float = 3.0
    ):
        self.base_url = base_url or os.getenv("BIFROST_BASE_URL", "http://localhost:8080/v1")
        self.api_key = api_key or os.getenv("BIFROST_API_KEY", "bifrost-local-key")
        self.default_model = default_model or os.getenv("MODEL_NAME", "gpt-4o-mini")
        self.timeout = timeout

        self._client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout
        )

    def probe_connection(self) -> Tuple[bool, str]:
        """Test gateway connectivity and return (status, message)."""
        import socket
        from urllib.parse import urlparse
        try:
            parsed = urlparse(self.base_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or (443 if parsed.scheme == "https" else 8080)
            with socket.create_connection((host, port), timeout=0.5):
                return True, f"Bifrost gateway reachable at {host}:{port}"
        except Exception as e:
            return False, f"Bifrost gateway unreachable at {self.base_url}: {e}"

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        fallback_mock: bool = True,
        request_id: Optional[str] = None
    ) -> Tuple[str, BifrostUsage]:
        """Execute chat completion through Bifrost gateway with exact token accounting."""
        target_model = model or self.default_model
        req_id = request_id or f"bf_req_{int(time.time()*1000)}_{os.urandom(3).hex()}"
        start_time = time.time()

        try:
            from agent.metrics import calculate_call_cost
            response = self._client.chat.completions.create(
                model=target_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_headers={"x-request-id": req_id}
            )
            elapsed = time.time() - start_time
            content = response.choices[0].message.content or ""

            if response.usage is not None:
                prompt_toks = response.usage.prompt_tokens if response.usage.prompt_tokens is not None else 0
                compl_toks = response.usage.completion_tokens if response.usage.completion_tokens is not None else 0
                total_toks = response.usage.total_tokens if response.usage.total_tokens is not None else (prompt_toks + compl_toks)
                cached_toks = None
                if hasattr(response.usage, "prompt_tokens_details") and response.usage.prompt_tokens_details:
                    cached_toks = getattr(response.usage.prompt_tokens_details, "cached_tokens", None)

                # Reconcile request ID from server response if available
                resp_id = getattr(response, "id", None) or req_id

                # Calculate cost with pricing catalog
                est_cost, cost_note = calculate_call_cost(
                    target_model,
                    prompt_toks,
                    compl_toks,
                    cached_toks
                )
            else:
                prompt_toks = 0
                compl_toks = 0
                total_toks = 0
                cached_toks = None
                resp_id = getattr(response, "id", None) or req_id
                est_cost = None
                cost_note = "Usage metadata omitted by provider; cost unavailable"

            usage = BifrostUsage(
                provider_reported_input_tokens=prompt_toks,
                provider_reported_output_tokens=compl_toks,
                provider_reported_total_tokens=total_toks,
                cached_tokens=cached_toks,
                input_tokens=prompt_toks,
                output_tokens=compl_toks,
                total_tokens=total_toks,
                request_id=resp_id,
                model=response.model or target_model,
                latency_seconds=elapsed,
                estimated_cost=est_cost,
                cost_calculation_note=cost_note,
                gateway_connected=True,
                provider="bifrost",
                is_simulated=False
            )
            return content, usage

        except (APIConnectionError, ConnectionError) as conn_err:
            elapsed = time.time() - start_time
            if fallback_mock:
                # Return deterministic mock payload for offline/preflight testing without failing build
                mock_content = f"// [OFFLINE BIFROST SIMULATION]\n// Proposed minimal patch for {target_model}"
                est_in = sum(len(m.get("content", "")) // 4 for m in messages)
                est_out = len(mock_content) // 4
                usage = BifrostUsage(
                    provider_reported_input_tokens=None,
                    provider_reported_output_tokens=None,
                    provider_reported_total_tokens=None,
                    cached_tokens=None,
                    input_tokens=est_in,
                    output_tokens=est_out,
                    total_tokens=est_in + est_out,
                    request_id=f"sim_{req_id}",
                    model=f"{target_model} (simulated-offline)",
                    latency_seconds=None,  # Latency unavailable for real provider
                    estimated_cost=None,    # Cost unavailable for simulation
                    cost_calculation_note="Cost unavailable for offline simulation",
                    gateway_connected=False,
                    provider="simulated-offline",
                    is_simulated=True,
                    simulation_note="Simulated response: Bifrost gateway offline or connection refused. Not a provider measurement."
                )
                return mock_content, usage
            raise conn_err

    @staticmethod
    def cross_check_usage(response: Any, recorded_usage: BifrostUsage) -> Dict[str, Any]:
        """Cross-check recorded usage against gateway response object."""
        if not response or not hasattr(response, "usage") or not response.usage:
            return {
                "verified": False,
                "reason": "Gateway response did not contain usage metadata",
                "diff_tokens": None
            }
        
        resp_prompt = response.usage.prompt_tokens or 0
        resp_compl = response.usage.completion_tokens or 0
        resp_total = response.usage.total_tokens or 0

        matches = (
            recorded_usage.provider_reported_input_tokens == resp_prompt and
            recorded_usage.provider_reported_output_tokens == resp_compl and
            recorded_usage.provider_reported_total_tokens == resp_total
        )

        return {
            "verified": matches,
            "response_prompt_tokens": resp_prompt,
            "response_completion_tokens": resp_compl,
            "response_total_tokens": resp_total,
            "recorded_input_tokens": recorded_usage.provider_reported_input_tokens,
            "recorded_output_tokens": recorded_usage.provider_reported_output_tokens,
            "recorded_total_tokens": recorded_usage.provider_reported_total_tokens,
            "diff_tokens": (recorded_usage.provider_reported_total_tokens or 0) - resp_total
        }
