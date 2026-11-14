"""Script to generate 12 reproducible benchmark tasks for TokenSlim.
Includes balanced task distribution: ordinary defects, selective context reduction,
deprecated APIs, changed SDKs, preserved CURRENT APIs, UNCERTAIN APIs, and model parameter updates.
"""
import json
import shutil
from pathlib import Path

TASKS_DIR = Path(__file__).resolve().parent / "tasks"

TASKS = [
    {
        "id": "task_01_factorial_off_by_one",
        "title": "Factorial Off-by-One Calculation Defect",
        "category": "ordinary_defect",
        "description": "Fix off-by-one bug in compute_factorial in calculator.py so that factorial(5) returns 120 instead of 24.",
        "expected_stale_outcome": "CURRENT",
        "test_command": "pytest test_calculator.py",
        "files": {
            "calculator.py": """def compute_factorial(n: int) -> int:
    \"\"\"Compute factorial of n.\"\"\"
    if n < 0:
        raise ValueError("Factorial undefined for negative numbers")
    if n == 0 or n == 1:
        return 1
    result = 1
    # Bug: range(1, n) stops at n-1
    for i in range(1, n):
        result *= i
    return result
""",
            "test_calculator.py": """from calculator import compute_factorial

def test_factorial_zero():
    assert compute_factorial(0) == 1

def test_factorial_one():
    assert compute_factorial(1) == 1

def test_factorial_five():
    # 5! = 120
    assert compute_factorial(5) == 120
"""
        }
    },
    {
        "id": "task_02_invoice_selective_context",
        "title": "Invoice ID Formatting in Large Service",
        "category": "selective_context",
        "description": "Fix format_invoice_id in invoice_service.py so invoice numbers are formatted with 'INV-' prefix and 5-digit zero padding.",
        "expected_stale_outcome": "CURRENT",
        "test_command": "pytest test_invoice.py",
        "files": {
            "invoice_service.py": """# Extensive enterprise invoice processing service
import datetime
from typing import Dict, List, Optional

def validate_currency(code: str) -> bool:
    return code in ("USD", "EUR", "GBP", "JPY")

def calculate_subtotal(items: List[Dict[str, float]]) -> float:
    return sum(item.get("qty", 0) * item.get("unit_price", 0.0) for item in items)

def calculate_tax(subtotal: float, tax_rate: float) -> float:
    return round(subtotal * tax_rate, 2)

def calculate_discount(subtotal: float, discount_pct: float) -> float:
    return round(subtotal * (discount_pct / 100.0), 2)

def format_currency_string(amount: float, currency: str) -> str:
    return f"{currency} {amount:,.2f}"

def format_invoice_id(invoice_num: int) -> str:
    \"\"\"Format numeric invoice ID with standard prefix and zero padding.\"\"\"
    # Bug: missing INV- prefix and zero padding
    return f"{invoice_num}"

def generate_invoice_metadata(invoice_num: int) -> Dict[str, str]:
    return {
        "invoice_id": format_invoice_id(invoice_num),
        "created_at": datetime.datetime.now().isoformat()
    }
""",
            "test_invoice.py": """from invoice_service import format_invoice_id, generate_invoice_metadata

def test_format_invoice_id():
    assert format_invoice_id(42) == "INV-00042"
    assert format_invoice_id(1) == "INV-00001"
    assert format_invoice_id(12345) == "INV-12345"
""",
            "tax_rules.py": """# Regional Tax Rule Engine
STATE_TAX_RATES = {
    "CA": 0.0725, "NY": 0.0400, "TX": 0.0625, "FL": 0.0600, "IL": 0.0625,
    "PA": 0.0600, "OH": 0.0575, "GA": 0.0400, "NC": 0.0475, "MI": 0.0600,
    "NJ": 0.06625, "VA": 0.0530, "WA": 0.0650, "AZ": 0.0560, "MA": 0.0625
}

def get_state_tax(state_code: str) -> float:
    return STATE_TAX_RATES.get(state_code.upper(), 0.05)

def is_tax_exempt(customer_type: str) -> bool:
    return customer_type.lower() in ("nonprofit", "government", "reseller")
""",
            "currency_tables.py": """# Global Currency Conversion Matrix
EXCHANGE_RATES = {
    "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "JPY": 155.20, "CAD": 1.36,
    "AUD": 1.52, "CHF": 0.89, "CNY": 7.24, "INR": 83.45, "BRL": 5.15
}

def convert_currency(amount: float, from_curr: str, to_curr: str) -> float:
    base = amount / EXCHANGE_RATES.get(from_curr, 1.0)
    return round(base * EXCHANGE_RATES.get(to_curr, 1.0), 2)
"""
        }
    },
    {
        "id": "task_03_pydantic_v2_dict_deprecation",
        "title": "Pydantic v2 .dict() Deprecation Migration",
        "category": "deprecated_api",
        "description": "Migrate user profile serializer in models.py from deprecated .dict() to Pydantic v2 .model_dump().",
        "expected_stale_outcome": "STALE",
        "test_command": "pytest test_models.py",
        "files": {
            "models.py": """from pydantic import BaseModel

class UserProfile(BaseModel):
    user_id: int
    username: str
    email: str

def serialize_user(user: UserProfile) -> dict:
    # Stale/deprecated API usage in Pydantic v2
    return user.dict()
""",
            "test_models.py": """from unittest.mock import MagicMock
from models import UserProfile, serialize_user

def test_serialize_user_calls_model_dump():
    user = UserProfile(user_id=1, username="alice", email="alice@example.com")
    # Verify serialization returns expected dict
    data = serialize_user(user)
    assert data == {"user_id": 1, "username": "alice", "email": "alice@example.com"}
    
    # Assert modern model_dump is used
    user_mock = MagicMock()
    user_mock.model_dump.return_value = {"mock": True}
    res = serialize_user(user_mock)
    assert user_mock.model_dump.called, "serialize_user must call model_dump() instead of deprecated dict()"
"""
        }
    },
    {
        "id": "task_04_pydantic_v2_parse_obj",
        "title": "Pydantic v2 parse_obj Deprecation Migration",
        "category": "deprecated_api",
        "description": "Migrate config loader in loader.py from deprecated .parse_obj() to Pydantic v2 .model_validate().",
        "expected_stale_outcome": "STALE",
        "test_command": "pytest test_loader.py",
        "files": {
            "loader.py": """from pydantic import BaseModel

class AppConfig(BaseModel):
    env: str
    port: int

def load_config(raw_dict: dict) -> AppConfig:
    # Stale/deprecated in Pydantic v2
    return AppConfig.parse_obj(raw_dict)
""",
            "test_loader.py": """from unittest.mock import MagicMock, patch
from loader import AppConfig, load_config

def test_load_config_calls_model_validate():
    # If deprecated parse_obj is called directly, raise error to verify migration to model_validate
    with patch.object(AppConfig, "parse_obj", side_effect=RuntimeError("parse_obj is deprecated")):
        cfg = load_config({"env": "prod", "port": 8080})
        assert cfg.env == "prod"
        assert cfg.port == 8080
"""
        }
    },
    {
        "id": "task_05_datetime_utcnow_deprecation",
        "title": "Python 3.12 datetime.utcnow Deprecation",
        "category": "deprecated_api",
        "description": "Replace deprecated datetime.utcnow() in session.py with timezone-aware datetime.now(timezone.utc).",
        "expected_stale_outcome": "STALE",
        "test_command": "pytest test_session.py",
        "files": {
            "session.py": """from datetime import datetime, timezone

class SessionManager:
    @staticmethod
    def create_session(user_id: str) -> dict:
        # Deprecated naive datetime in Python 3.12+
        created_at = datetime.utcnow()
        return {
            "user_id": user_id,
            "created_at": created_at
        }
""",
            "test_session.py": """from session import SessionManager

def test_session_has_timezone_aware_timestamp():
    session = SessionManager.create_session("usr_123")
    dt = session["created_at"]
    # Deprecated utcnow() produces naive datetimes where tzinfo is None
    assert dt.tzinfo is not None, "Timestamp must be timezone-aware (tzinfo is not None)"
"""
        }
    },
    {
        "id": "task_06_openai_sdk_v1_chat_completion",
        "title": "OpenAI Python SDK v1.0 Client Migration",
        "category": "changed_sdk",
        "description": "Migrate llm_gateway.py from removed openai.ChatCompletion.create() to modern client.chat.completions.create().",
        "expected_stale_outcome": "STALE",
        "test_command": "pytest test_llm_gateway.py",
        "files": {
            "llm_gateway.py": """import openai

def query_model(prompt: str, model: str = "gpt-4o-mini") -> str:
    # Removed global method in OpenAI SDK v1.0+
    response = openai.ChatCompletion.create(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content
""",
            "test_llm_gateway.py": """from unittest.mock import MagicMock, patch
import llm_gateway

def test_query_model_uses_instantiated_client():
    with patch("openai.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content="Mock response"))
        ]
        res = llm_gateway.query_model("Hello")
        assert res == "Mock response"
        assert mock_client.chat.completions.create.called
"""
        }
    },
    {
        "id": "task_07_collections_abc_mapping",
        "title": "Python 3.10 collections.Mapping Removal Migration",
        "category": "deprecated_api",
        "description": "Migrate mapping_utils.py from removed collections.Mapping to standard collections.abc.Mapping.",
        "expected_stale_outcome": "STALE",
        "test_command": "pytest test_mapping_utils.py",
        "files": {
            "mapping_utils.py": """# Stale import removed in Python 3.10+
from collections import Mapping

def is_mapping_type(obj) -> bool:
    return isinstance(obj, Mapping)
""",
            "test_mapping_utils.py": """import pytest

def test_is_mapping_type():
    from mapping_utils import is_mapping_type
    assert is_mapping_type({"a": 1}) is True
    assert is_mapping_type([1, 2, 3]) is False
"""
        }
    },
    {
        "id": "task_08_current_api_preserved",
        "title": "HTTP Status Code Fix While Preserving Current Pydantic Field APIs",
        "category": "preserve_current",
        "description": "Fix status code in create_item from 200 to 201 without altering valid Pydantic Field annotations.",
        "expected_stale_outcome": "CURRENT",
        "test_command": "pytest test_api_handler.py",
        "files": {
            "api_handler.py": """from pydantic import BaseModel, Field

class ItemPayload(BaseModel):
    name: str = Field(..., min_length=1, description="Item name")
    price: float = Field(..., gt=0.0, description="Price must be positive")

def handle_create_item(payload_dict: dict) -> dict:
    item = ItemPayload.model_validate(payload_dict)
    # Bug: returns 200 instead of HTTP 201 Created
    return {
        "status_code": 200,
        "item": item.model_dump()
    }
""",
            "test_api_handler.py": """from api_handler import handle_create_item, ItemPayload

def test_create_item_status_and_schema():
    res = handle_create_item({"name": "Widget", "price": 9.99})
    assert res["status_code"] == 201
    assert res["item"]["name"] == "Widget"
    # Ensure Field definitions were preserved
    assert ItemPayload.model_fields["price"].description == "Price must be positive"
"""
        }
    },
    {
        "id": "task_09_uncertain_obscure_math",
        "title": "Proprietary Algorithm Base-Case Repair (Uncertain Documentation)",
        "category": "uncertain_evidence",
        "description": "Fix base-case bug in internal proprietary function _custom_fast_exp without replacing the custom algorithm.",
        "expected_stale_outcome": "UNCERTAIN",
        "test_command": "pytest test_math_internal.py",
        "files": {
            "math_internal.py": """def _custom_fast_exp(base: int, exp: int) -> int:
    \"\"\"Internal proprietary fast modular exponentiation helper.\"\"\"
    # Bug: base case for exponent 0 should be 1, not 0
    if exp == 0:
        return 0
    if exp == 1:
        return base
    half = _custom_fast_exp(base, exp // 2)
    if exp % 2 == 0:
        return half * half
    return base * half * half
""",
            "test_math_internal.py": """from math_internal import _custom_fast_exp

def test_fast_exp_zero():
    # Any non-zero base to power 0 is 1
    assert _custom_fast_exp(2, 0) == 1
    assert _custom_fast_exp(5, 0) == 1

def test_fast_exp_positive():
    assert _custom_fast_exp(2, 3) == 8
    assert _custom_fast_exp(3, 4) == 81
"""
        }
    },
    {
        "id": "task_10_deprecated_model_param",
        "title": "Shutdown Model Name Configuration Update",
        "category": "deprecated_param",
        "description": "Update deprecated and decommissioned model name 'text-davinci-003' to 'gpt-4o-mini' in settings.py.",
        "expected_stale_outcome": "STALE",
        "test_command": "pytest test_settings.py",
        "files": {
            "settings.py": """# Model configuration settings
DEFAULT_MODEL = "text-davinci-003"
MAX_TOKENS = 1000
TEMPERATURE = 0.2
""",
            "test_settings.py": """import settings

def test_active_model_configured():
    # text-davinci-003 was decommissioned by OpenAI
    assert settings.DEFAULT_MODEL == "gpt-4o-mini"
"""
        }
    },
    {
        "id": "task_11_string_reversal_edge_cases",
        "title": "Whitespace Edge-Case in Word Reversal",
        "category": "ordinary_defect",
        "description": "Fix reverse_words in text_cleaner.py to correctly normalize multiple consecutive whitespace and handle empty strings.",
        "expected_stale_outcome": "CURRENT",
        "test_command": "pytest test_text_cleaner.py",
        "files": {
            "text_cleaner.py": """def reverse_words(text: str) -> str:
    \"\"\"Reverse order of words in text, preserving single spacing.\"\"\"
    # Bug: naive split(' ') preserves empty string tokens on multiple spaces
    words = text.split(" ")
    return " ".join(reversed(words))
""",
            "test_text_cleaner.py": """from text_cleaner import reverse_words

def test_reverse_words_standard():
    assert reverse_words("the sky is blue") == "blue is sky the"

def test_reverse_words_multiple_spaces():
    assert reverse_words("  hello   world  ") == "world hello"

def test_reverse_words_empty():
    assert reverse_words("") == ""
"""
        }
    },
    {
        "id": "task_12_pkg_resources_migration",
        "title": "pkg_resources Deprecation Migration",
        "category": "deprecated_api",
        "description": "Migrate asset_reader.py away from deprecated pkg_resources to standard library importlib.resources.",
        "expected_stale_outcome": "STALE",
        "test_command": "pytest test_asset_reader.py",
        "files": {
            "asset_reader.py": """# Stale: pkg_resources is deprecated
import pkg_resources

def read_package_asset(package_name: str, asset_filename: str) -> str:
    # Stale API
    return pkg_resources.resource_string(package_name, asset_filename).decode("utf-8")
""",
            "test_asset_reader.py": """from unittest.mock import patch, MagicMock
import asset_reader

def test_read_package_asset_uses_importlib():
    with patch("importlib.resources.files") as mock_files:
        mock_asset = MagicMock()
        mock_asset.read_text.return_value = "asset content"
        mock_files.return_value.joinpath.return_value = mock_asset
        
        content = asset_reader.read_package_asset("my_pkg", "data.txt")
        assert content == "asset content"
"""
        }
    }
]

def create_all_tasks():
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    created_count = 0
    for task in TASKS:
        t_dir = TASKS_DIR / task["id"]
        t_dir.mkdir(parents=True, exist_ok=True)

        # Write task metadata
        meta = {
            "task_id": task["id"],
            "title": task["title"],
            "category": task["category"],
            "description": task["description"],
            "expected_stale_outcome": task["expected_stale_outcome"],
            "test_command": task["test_command"]
        }
        (t_dir / "task.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        # Write files
        for fname, content in task["files"].items():
            (t_dir / fname).write_text(content, encoding="utf-8")

        created_count += 1
        print(f"Created task: {task['id']}")

    print(f"Successfully generated {created_count} benchmark tasks.")

if __name__ == "__main__":
    create_all_tasks()
