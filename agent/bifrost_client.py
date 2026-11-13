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
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    latency_seconds: float = 0.0
    estimated_cost: Optional[float] = None
    gateway_connected: bool = True
    provider: Optional[str] = "bifrost"

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
        fallback_mock: bool = True
    ) -> Tuple[str, BifrostUsage]:
        """Execute chat completion through Bifrost gateway with exact token accounting."""
        target_model = model or self.default_model
        start_time = time.time()

        try:
            response = self._client.chat.completions.create(
                model=target_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            elapsed = time.time() - start_time
            content = response.choices[0].message.content or ""

            usage = BifrostUsage(
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                total_tokens=response.usage.total_tokens if response.usage else 0,
                model=response.model or target_model,
                latency_seconds=elapsed,
                gateway_connected=True,
                provider="bifrost"
            )
            return content, usage

        except (APIConnectionError, ConnectionError) as conn_err:
            elapsed = time.time() - start_time
            if fallback_mock:
                # Return deterministic mock payload for offline/preflight testing without failing build
                mock_content = f"// [OFFLINE BIFROST SIMULATION]\n// Proposed minimal patch for {target_model}"
                usage = BifrostUsage(
                    input_tokens=sum(len(m.get("content", "")) // 4 for m in messages),
                    output_tokens=len(mock_content) // 4,
                    total_tokens=(sum(len(m.get("content", "")) // 4 for m in messages)) + (len(mock_content) // 4),
                    model=f"{target_model} (mock-offline)",
                    latency_seconds=elapsed,
                    gateway_connected=False,
                    provider="mock-fallback"
                )
                return mock_content, usage
            raise conn_err
