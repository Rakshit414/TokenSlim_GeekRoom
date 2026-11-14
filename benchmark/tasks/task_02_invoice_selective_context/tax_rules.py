# Regional Tax Rule Engine
STATE_TAX_RATES = {
    "CA": 0.0725, "NY": 0.0400, "TX": 0.0625, "FL": 0.0600, "IL": 0.0625,
    "PA": 0.0600, "OH": 0.0575, "GA": 0.0400, "NC": 0.0475, "MI": 0.0600,
    "NJ": 0.06625, "VA": 0.0530, "WA": 0.0650, "AZ": 0.0560, "MA": 0.0625
}

def get_state_tax(state_code: str) -> float:
    return STATE_TAX_RATES.get(state_code.upper(), 0.05)

def is_tax_exempt(customer_type: str) -> bool:
    return customer_type.lower() in ("nonprofit", "government", "reseller")
