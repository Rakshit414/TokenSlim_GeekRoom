"""TokenSlim Stale-Answer Detection Engine.
Detects outdated technical assumptions, retrieves authoritative evidence via Tavily,
classifies claims (CURRENT, STALE, UNCERTAIN), and generates minimal correction recommendations.
"""
import os
import re
import uuid
import time
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse
from pydantic import BaseModel, Field

from agent.docs_check import TavilyDocsClient, TavilyEvidence, TavilyVerificationResult
from server.database import save_stale_detection_run

# Map technologies to official authoritative documentation domains
TECH_AUTHORITY_DOMAINS: Dict[str, List[str]] = {
    "python": ["docs.python.org"],
    "pydantic": ["docs.pydantic.dev", "pydantic.dev"],
    "openai": ["platform.openai.com", "openai.com", "github.com/openai"],
    "anthropic": ["docs.anthropic.com", "anthropic.com"],
    "fastapi": ["fastapi.tiangolo.com"],
    "pandas": ["pandas.pydata.org"],
    "numpy": ["numpy.org"],
    "langchain": ["python.langchain.com", "js.langchain.com"],
    "sqlalchemy": ["docs.sqlalchemy.org"],
    "docker": ["docs.docker.com"],
    "pytest": ["docs.pytest.org"]
}

# Known obsolescence patterns for heuristic claim extraction from code/tasks
KNOWN_OBSOLESCENCE_PATTERNS = [
    {
        "pattern": r"\b(\w+)\.dict\(\)",
        "tech": "pydantic",
        "description": "pydantic.BaseModel.dict() method usage",
        "expected_modern": ".model_dump()",
        "hint": "Deprecated in Pydantic v2; replaced by model_dump()"
    },
    {
        "pattern": r"\b(\w+)\.parse_obj\(",
        "tech": "pydantic",
        "description": "pydantic.BaseModel.parse_obj() method usage",
        "expected_modern": ".model_validate()",
        "hint": "Deprecated in Pydantic v2; replaced by model_validate()"
    },
    {
        "pattern": r"datetime\.(?:datetime\.)?utcnow\(\)",
        "tech": "python",
        "description": "datetime.utcnow() method usage",
        "expected_modern": "datetime.now(timezone.utc)",
        "hint": "Deprecated in Python 3.12+; produces naive datetimes prone to timezone bugs"
    },
    {
        "pattern": r"openai\.ChatCompletion\.create\(",
        "tech": "openai",
        "description": "Legacy openai.ChatCompletion.create() API call",
        "expected_modern": "client.chat.completions.create()",
        "hint": "Removed in OpenAI Python SDK v1.0+; requires instantiated OpenAI client"
    },
    {
        "pattern": r"openai\.Completion\.create\(",
        "tech": "openai",
        "description": "Legacy openai.Completion.create() completions API",
        "expected_modern": "client.chat.completions.create()",
        "hint": "Legacy completions API endpoint superseded by ChatCompletions"
    },
    {
        "pattern": r"import\s+pkg_resources",
        "tech": "python",
        "description": "pkg_resources module import",
        "expected_modern": "import importlib.resources or importlib.metadata",
        "hint": "pkg_resources is deprecated and slated for removal; use importlib"
    },
    {
        "pattern": r"\.append\(.*ignore_index\s*=\s*True\)",
        "tech": "pandas",
        "description": "pandas.DataFrame.append() usage",
        "expected_modern": "pandas.concat([df1, df2])",
        "hint": "DataFrame.append was removed in pandas 2.0"
    },
    {
        "pattern": r"model\s*=\s*[\"'](?:gpt-3\.5-turbo-0301|text-davinci-003|code-davinci-002)[\"']",
        "tech": "openai",
        "description": "Deprecated OpenAI model name",
        "expected_modern": "gpt-4o-mini",
        "hint": "Model has been shut down and deprecated by OpenAI"
    }
]

class ClaimEvidence(BaseModel):
    evidence_id: str
    claim_id: str
    url: str
    domain: str
    title: str
    excerpt: str
    relevance_score: float = 0.0
    retrieved_at: str
    is_simulated: bool = False

class Claim(BaseModel):
    claim_id: str
    claim_text: str
    file_path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    technology: str = "general"
    version: Optional[str] = None
    priority: str = "medium"  # "high", "medium", "low"
    classification: str = "UNCERTAIN"  # "CURRENT", "STALE", "UNCERTAIN"
    confidence: float = 0.0
    reasoning: str = ""
    recommended_correction: Optional[str] = None
    suggested_patch: Optional[str] = None
    is_simulated: bool = False
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))

class StaleDetectionRun(BaseModel):
    run_id: str
    task_description: str
    status: str = "completed"
    claims: List[Claim] = Field(default_factory=list)
    evidence_records: List[ClaimEvidence] = Field(default_factory=list)
    searches_executed: int = 0
    search_budget: int = 5
    is_simulated: bool = False
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))

    @property
    def stale_claims(self) -> List[Claim]:
        return [c for c in self.claims if c.classification == "STALE"]

    @property
    def current_claims(self) -> List[Claim]:
        return [c for c in self.claims if c.classification == "CURRENT"]

    @property
    def uncertain_claims(self) -> List[Claim]:
        return [c for c in self.claims if c.classification == "UNCERTAIN"]


class StaleAnswerDetector:
    """Core autonomous stale-answer detection engine."""

    def __init__(self, tavily_client: Optional[TavilyDocsClient] = None, search_budget: int = 5):
        self.tavily = tavily_client or TavilyDocsClient()
        self.search_budget = search_budget
        # Query cache to prevent duplicate search calls within runs
        self._query_cache: Dict[str, TavilyVerificationResult] = {}

    def extract_claims_from_context(
        self,
        task: str,
        code_snippets: Optional[Dict[str, str]] = None,
        explicit_claims: Optional[List[Dict[str, Any]]] = None
    ) -> List[Claim]:
        """Extract checkable technical claims from task directive, codebase snippets, or explicit inputs."""
        claims: List[Claim] = []
        now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

        # 1. Ingest any user-provided or explicit claims
        if explicit_claims:
            for item in explicit_claims:
                cid = item.get("claim_id") or f"claim_{uuid.uuid4().hex[:8]}"
                claims.append(Claim(
                    claim_id=cid,
                    claim_text=item.get("claim_text", item.get("claim", "")),
                    file_path=item.get("file_path"),
                    line_start=item.get("line_start"),
                    line_end=item.get("line_end"),
                    technology=item.get("technology", "general"),
                    version=item.get("version"),
                    priority=item.get("priority", "high"),
                    classification=item.get("classification", "UNCERTAIN"),
                    is_simulated=item.get("is_simulated", False),
                    created_at=now_str
                ))

        # 2. Extract technical claims from code files using obsolescence patterns
        if code_snippets:
            for file_path, content in code_snippets.items():
                lines = content.splitlines()
                for idx, line in enumerate(lines, 1):
                    for pat_info in KNOWN_OBSOLESCENCE_PATTERNS:
                        match = re.search(pat_info["pattern"], line)
                        if match:
                            claim_text = f"{pat_info['description']} in {os.path.basename(file_path)}: {line.strip()}"
                            # Avoid duplicates for same line
                            if not any(c.file_path == file_path and c.line_start == idx for c in claims):
                                claims.append(Claim(
                                    claim_id=f"claim_{uuid.uuid4().hex[:8]}",
                                    claim_text=claim_text,
                                    file_path=file_path,
                                    line_start=idx,
                                    line_end=idx,
                                    technology=pat_info["tech"],
                                    priority="high",
                                    classification="UNCERTAIN",
                                    reasoning=f"Potential deprecation pattern identified: {pat_info['hint']}",
                                    created_at=now_str
                                ))

        # 3. Analyze task description for targeted library / migration claims
        task_lower = task.lower()
        if "pydantic v2" in task_lower or "pydantic 2" in task_lower or "migrate to pydantic" in task_lower:
            if not any("pydantic" in c.technology for c in claims):
                claims.append(Claim(
                    claim_id=f"claim_{uuid.uuid4().hex[:8]}",
                    claim_text="Pydantic models should use v2 methods (model_validate, model_dump) instead of v1 (parse_obj, dict)",
                    technology="pydantic",
                    version="2.x",
                    priority="high",
                    classification="UNCERTAIN",
                    created_at=now_str
                ))
        if "openai v1" in task_lower or "openai 1.0" in task_lower:
            if not any("openai" in c.technology for c in claims):
                claims.append(Claim(
                    claim_id=f"claim_{uuid.uuid4().hex[:8]}",
                    claim_text="OpenAI client initialization requires instantiated client (OpenAI()) instead of global openai module methods",
                    technology="openai",
                    version=">=1.0",
                    priority="high",
                    classification="UNCERTAIN",
                    created_at=now_str
                ))

        return claims

    def verify_claim(
        self,
        claim: Claim,
        searches_remaining: int
    ) -> Tuple[Claim, List[ClaimEvidence], int]:
        """Search authoritative documentation using Tavily and classify claim as CURRENT, STALE, or UNCERTAIN."""
        evidence_list: List[ClaimEvidence] = []
        now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

        # If search budget exhausted, mark as UNCERTAIN without crashing
        if searches_remaining <= 0:
            claim.classification = "UNCERTAIN"
            claim.confidence = 0.0
            claim.reasoning = "Search budget exhausted; claim remains UNCERTAIN without verified documentation evidence."
            return claim, evidence_list, 0

        # Construct targeted documentation search query
        query = self._build_search_query(claim)
        domains = TECH_AUTHORITY_DOMAINS.get(claim.technology.lower())

        # Check deduplication cache
        cache_key = f"{claim.technology.lower()}:{query.lower()}"
        searches_spent = 0
        if cache_key in self._query_cache:
            search_result = self._query_cache[cache_key]
        else:
            try:
                search_result = self.tavily.search_docs(
                    query=query,
                    domains=domains,
                    max_results=3,
                    fallback_mock=True
                )
                self._query_cache[cache_key] = search_result
                searches_spent = 1
            except Exception as e:
                claim.classification = "UNCERTAIN"
                claim.confidence = 0.0
                claim.reasoning = f"External documentation retrieval failed: {str(e)}"
                return claim, evidence_list, 1

        is_simulated = search_result.is_simulated

        # Convert search results to ClaimEvidence records
        for item in search_result.evidence_items:
            domain = urlparse(item.source_url).netloc if item.source_url else "unknown"
            evidence_list.append(ClaimEvidence(
                evidence_id=f"ev_{uuid.uuid4().hex[:8]}",
                claim_id=claim.claim_id,
                url=item.source_url,
                domain=domain,
                title=item.source_title,
                excerpt=item.snippet,
                relevance_score=item.score,
                retrieved_at=item.date_retrieved,
                is_simulated=item.is_simulated
            ))

        # Classify claim based on retrieved evidence
        classification, confidence, reasoning, correction, patch = self._classify_evidence(
            claim, evidence_list, search_result
        )

        claim.classification = classification
        claim.confidence = confidence
        claim.reasoning = reasoning
        claim.recommended_correction = correction
        claim.suggested_patch = patch
        claim.is_simulated = is_simulated

        return claim, evidence_list, searches_spent

    def run_detection(
        self,
        task: str,
        code_snippets: Optional[Dict[str, str]] = None,
        explicit_claims: Optional[List[Dict[str, Any]]] = None,
        max_searches: Optional[int] = None,
        persist: bool = True
    ) -> StaleDetectionRun:
        """Execute complete stale-answer detection pipeline."""
        budget = max_searches if max_searches is not None else self.search_budget
        run_id = f"stale_run_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

        # Extract claims
        extracted = self.extract_claims_from_context(task, code_snippets, explicit_claims)

        processed_claims: List[Claim] = []
        all_evidence: List[ClaimEvidence] = []
        searches_executed = 0
        is_any_simulated = not self.tavily.is_configured

        for claim in extracted:
            searches_left = budget - searches_executed
            verified_claim, evidence, spent = self.verify_claim(claim, searches_left)
            searches_executed += spent
            processed_claims.append(verified_claim)
            all_evidence.extend(evidence)
            if verified_claim.is_simulated:
                is_any_simulated = True

        run_record = StaleDetectionRun(
            run_id=run_id,
            task_description=task,
            status="completed",
            claims=processed_claims,
            evidence_records=all_evidence,
            searches_executed=searches_executed,
            search_budget=budget,
            is_simulated=is_any_simulated,
            created_at=now_str
        )

        if persist:
            save_stale_detection_run(
                run_id=run_record.run_id,
                task_description=run_record.task_description,
                status=run_record.status,
                claims=[c.model_dump() for c in run_record.claims],
                evidence_records=[e.model_dump() for e in run_record.evidence_records],
                searches_executed=run_record.searches_executed,
                search_budget=run_record.search_budget,
                is_simulated=run_record.is_simulated
            )

        return run_record

    def _build_search_query(self, claim: Claim) -> str:
        """Formulate precise documentation search query for a claim."""
        tech = claim.technology
        ver = f" {claim.version}" if claim.version else ""
        return f"{tech}{ver} documentation {claim.claim_text}".strip()

    def _classify_evidence(
        self,
        claim: Claim,
        evidence_list: List[ClaimEvidence],
        search_result: TavilyVerificationResult
    ) -> Tuple[str, float, str, Optional[str], Optional[str]]:
        """Classify claim as CURRENT, STALE, or UNCERTAIN using retrieved documentation evidence.
        IMPORTANT: Never classify as STALE merely because no evidence was retrieved.
        """
        if not evidence_list:
            return (
                "UNCERTAIN",
                0.0,
                "No documentation evidence retrieved from search provider. Preserved as UNCERTAIN without drawing unsupported conclusions.",
                None,
                None
            )

        combined_text = " ".join([e.title + " " + e.excerpt for e in evidence_list]).lower()

        # Check for conflicting signals
        has_deprecation_signal = any(term in combined_text for term in [
            "deprecated", "removed in", "no longer supported", "will be removed",
            "is obsolete", "superseded by", "migration guide", "breaking change"
        ])
        has_active_signal = any(term in combined_text for term in [
            "current", "stable", "recommended", "standard usage", "supported", "active"
        ])

        # Specific technology deprecation keywords
        tech_lower = claim.technology.lower()
        claim_lower = claim.claim_text.lower()

        # Check for STALE evidence
        if has_deprecation_signal:
            top_ev = max(evidence_list, key=lambda x: x.relevance_score) if evidence_list else None
            source_ref = f"{top_ev.title} ({top_ev.url})" if top_ev else "documentation"

            explanation = (
                f"Authoritative documentation from {source_ref} indicates that '{claim.claim_text}' "
                f"is deprecated, removed, or superseded in modern {claim.technology}."
            )

            # Formulate recommended correction
            correction, patch = self._generate_recommendation(claim, combined_text)
            confidence = min(0.95, round(0.70 + (top_ev.relevance_score if top_ev else 0.0) * 0.25, 2))
            return "STALE", confidence, explanation, correction, patch

        # Check for CURRENT evidence
        if has_active_signal or any(keyword in combined_text for keyword in [tech_lower, "api", "reference", "guide"]):
            top_ev = max(evidence_list, key=lambda x: x.relevance_score) if evidence_list else None
            source_ref = f"{top_ev.title} ({top_ev.url})" if top_ev else "documentation"

            explanation = (
                f"Official documentation from {source_ref} supports '{claim.claim_text}' "
                f"as current and valid for {claim.technology}."
            )
            confidence = min(0.90, round(0.65 + (top_ev.relevance_score if top_ev else 0.0) * 0.25, 2))
            return "CURRENT", confidence, explanation, None, None

        # If evidence is ambiguous, return UNCERTAIN
        return (
            "UNCERTAIN",
            0.30,
            "Retrieved documentation snippets do not provide conclusive evidence supporting or contradicting the claim.",
            None,
            None
        )

    def _generate_recommendation(self, claim: Claim, context_text: str) -> Tuple[str, Optional[str]]:
        """Generate structured correction recommendation and suggested minimal code patch."""
        claim_lower = claim.claim_text.lower()

        if "dict()" in claim_lower or "pydantic" in claim_lower and "dict" in claim_lower:
            rec = "Replace deprecated `.dict()` method with `.model_dump()` in Pydantic v2."
            patch = "- return model.dict()\n+ return model.model_dump()"
            return rec, patch

        if "parse_obj" in claim_lower or "pydantic" in claim_lower and "parse" in claim_lower:
            rec = "Replace deprecated `.parse_obj(data)` method with `.model_validate(data)` in Pydantic v2."
            patch = "- return MyModel.parse_obj(payload)\n+ return MyModel.model_validate(payload)"
            return rec, patch

        if "utcnow" in claim_lower:
            rec = "Replace deprecated `datetime.utcnow()` with timezone-aware `datetime.now(timezone.utc)`."
            patch = "- now = datetime.utcnow()\n+ now = datetime.now(timezone.utc)"
            return rec, patch

        if "chatcompletion.create" in claim_lower:
            rec = "Instantiate `client = OpenAI()` and invoke `client.chat.completions.create(...)` in OpenAI v1.0+."
            patch = "- response = openai.ChatCompletion.create(...)\n+ client = OpenAI()\n+ response = client.chat.completions.create(...)"
            return rec, patch

        if "pkg_resources" in claim_lower:
            rec = "Migrate from deprecated `pkg_resources` to `importlib.metadata` or `importlib.resources`."
            patch = "- import pkg_resources\n+ import importlib.metadata"
            return rec, patch

        # General recommendation
        rec = f"Update deprecated {claim.technology} syntax to the current documented alternative based on official migration guide."
        patch = None
        return rec, patch
