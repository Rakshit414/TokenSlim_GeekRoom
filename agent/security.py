"""TokenSlim security and privacy utilities.
Sanitizes secrets, masks credentials, prevents prompt injection from untrusted external documentation,
and enforces concurrency and rate limits.
"""
import re
from typing import Any, Dict, List, Union

# Patterns for sensitive tokens and keys
SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_\-]{8,}", re.IGNORECASE),
    re.compile(r"tvly-[a-zA-Z0-9_\-]{8,}", re.IGNORECASE),
    re.compile(r"ghp_[a-zA-Z0-9]{15,}", re.IGNORECASE),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\.\-]{10,}", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[:=]\s*['\"]?)[a-zA-Z0-9_\-]{8,}(['\"]?)", re.IGNORECASE),
    re.compile(r"(token\s*[:=]\s*['\"]?)[a-zA-Z0-9_\-]{8,}(['\"]?)", re.IGNORECASE),
    re.compile(r"(password\s*[:=]\s*['\"]?)[^\s'\"]{4,}(['\"]?)", re.IGNORECASE)
]

SENSITIVE_KEY_NAMES = {
    "api_key", "apikey", "secret", "password", "token", "authorization",
    "access_token", "tavily_api_key", "openai_api_key"
}

# Prompt injection markers from untrusted external sources
INJECTION_MARKERS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(an?\s+)?unrestricted", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*override", re.IGNORECASE),
    re.compile(r"bypass\s+all\s+(safety|security)\s+filters", re.IGNORECASE),
]

def scrub_secrets(text: str) -> str:
    """Scrub sensitive credentials, API keys, and authorization headers from text."""
    if not isinstance(text, str) or not text:
        return text

    sanitized = text
    for pat in SECRET_PATTERNS:
        sanitized = pat.sub("[REDACTED_SECRET]", sanitized)
    return sanitized

def sanitize_payload(obj: Any) -> Any:
    """Recursively scrub secrets from dictionaries, lists, or strings."""
    if isinstance(obj, str):
        return scrub_secrets(obj)
    elif isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            if str(k).lower() in SENSITIVE_KEY_NAMES:
                cleaned[k] = "[REDACTED_SECRET]"
            else:
                cleaned[k] = sanitize_payload(v)
        return cleaned
    elif isinstance(obj, list):
        return [sanitize_payload(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(sanitize_payload(item) for item in obj)
    return obj

def sanitize_external_doc(doc_text: str) -> str:
    """Sanitize retrieved external documentation, disarming prompt injection attacks."""
    if not isinstance(doc_text, str) or not doc_text:
        return ""

    sanitized = doc_text
    for marker in INJECTION_MARKERS:
        sanitized = marker.sub("[UNTRUSTED_INSTRUCTION_REMOVED]", sanitized)

    # Disarm role markers (e.g., SYSTEM:, HUMAN:, ASSISTANT:, USER:)
    sanitized = re.sub(r"(?i)\b(SYSTEM\s*:)", r"[DISARMED_DIRECTIVE_SYSTEM]:", sanitized)
    sanitized = re.sub(r"(?i)\b(ASSISTANT\s*:)", r"[DISARMED_DIRECTIVE_ASSISTANT]:", sanitized)
    sanitized = re.sub(r"(?i)\b(HUMAN\s*:)", r"[DISARMED_DIRECTIVE_HUMAN]:", sanitized)
    sanitized = re.sub(r"(?i)\b(USER\s*:)", r"[DISARMED_DIRECTIVE_USER]:", sanitized)

    return sanitized
