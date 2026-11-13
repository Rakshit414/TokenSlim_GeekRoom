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

class TavilyVerificationResult(BaseModel):
    query: str
    evidence_items: List[TavilyEvidence]
    is_live: bool = True
    error_message: Optional[str] = None
    search_duration_seconds: float = 0.0

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
                            source_title="Mock Authoritative Reference (TAVILY_API_KEY not set)",
                            source_url="https://docs.mock.dev/reference",
                            snippet=f"Documentation verification simulation for query: {query}",
                            score=0.95,
                            date_retrieved=date_str
                        )
                    ],
                    is_live=False,
                    error_message="TAVILY_API_KEY is not configured in environment.",
                    search_duration_seconds=time.time() - start_time
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
                        date_retrieved=date_str
                    )
                )

            return TavilyVerificationResult(
                query=query,
                evidence_items=evidence_items,
                is_live=True,
                search_duration_seconds=elapsed
            )

        except Exception as e:
            elapsed = time.time() - start_time
            if fallback_mock:
                return TavilyVerificationResult(
                    query=query,
                    evidence_items=[],
                    is_live=False,
                    error_message=f"Tavily search failed: {e}",
                    search_duration_seconds=elapsed
                )
            raise e
