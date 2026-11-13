"""Tavily search and documentation verification integration.
Implements the retrieval engine for the Stale-Answer Detector.
"""
import os
import time
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from tavily import TavilyClient

class TavilyEvidence(BaseModel):
    query: str
    source_title: str
    source_url: str
    snippet: str
    score: float = 0.0
    date_retrieved: str
    is_simulated: bool = False

class TavilyVerificationResult(BaseModel):
    query: str
    evidence_items: List[TavilyEvidence]
    is_live: bool = True
    is_simulated: bool = False
    simulation_note: Optional[str] = None
    error_message: Optional[str] = None
    search_duration_seconds: Optional[float] = None

class TavilyDocsClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY", "")
        self._client = TavilyClient(api_key=self.api_key) if self.api_key else None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def search_docs(
        self,
        query: str,
        domains: Optional[List[str]] = None,
        max_results: int = 3,
        fallback_mock: bool = True
    ) -> TavilyVerificationResult:
        """Search authoritative documentation using Tavily API."""
        start_time = time.time()
        date_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

        # If not configured or offline, handle gracefully
        if not self._client:
            if fallback_mock:
                return TavilyVerificationResult(
                    query=query,
                    evidence_items=[
                        TavilyEvidence(
                            query=query,
                            source_title="[SIMULATED - OFFLINE] Documentation Reference",
                            source_url="https://mock.invalid/simulated-reference",
                            snippet=f"[SIMULATION] Mock documentation excerpt for query: {query}",
                            score=0.0,  # Score 0 for simulated evidence
                            date_retrieved=date_str,
                            is_simulated=True
                        )
                    ],
                    is_live=False,
                    is_simulated=True,
                    simulation_note="Simulated documentation: TAVILY_API_KEY is not set. Not a live search result.",
                    error_message="TAVILY_API_KEY is not configured in environment.",
                    search_duration_seconds=None
                )
            raise ValueError("TAVILY_API_KEY is not configured.")

        try:
            # Query Tavily search with domain preferences
            search_kwargs: Dict[str, Any] = {
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_answer": True
            }
            if domains:
                search_kwargs["include_domains"] = domains

            response = self._client.search(**search_kwargs)
            elapsed = time.time() - start_time

            evidence_items = []
            results = response.get("results", [])
            for res in results:
                evidence_items.append(
                    TavilyEvidence(
                        query=query,
                        source_title=res.get("title", "Untitled Source"),
                        source_url=res.get("url", ""),
                        snippet=res.get("content", "")[:500],  # Limit snippet length
                        score=res.get("score", 0.0),
                        date_retrieved=date_str,
                        is_simulated=False
                    )
                )

            return TavilyVerificationResult(
                query=query,
                evidence_items=evidence_items,
                is_live=True,
                is_simulated=False,
                search_duration_seconds=elapsed
            )

        except Exception as e:
            elapsed = time.time() - start_time
            if fallback_mock:
                return TavilyVerificationResult(
                    query=query,
                    evidence_items=[],
                    is_live=False,
                    is_simulated=True,
                    simulation_note=f"Simulated empty result: Tavily search call failed ({e}).",
                    error_message=f"Tavily search failed: {e}",
                    search_duration_seconds=None
                )
            raise e
