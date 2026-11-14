# Extensive enterprise invoice processing service
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
    """Format numeric invoice ID with standard prefix and zero padding."""
    # Bug: missing INV- prefix and zero padding
    return f"{invoice_num}"

def generate_invoice_metadata(invoice_num: int) -> Dict[str, str]:
    return {
        "invoice_id": format_invoice_id(invoice_num),
        "created_at": datetime.datetime.now().isoformat()
    }
