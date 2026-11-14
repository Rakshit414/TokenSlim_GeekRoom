# Global Currency Conversion Matrix
EXCHANGE_RATES = {
    "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "JPY": 155.20, "CAD": 1.36,
    "AUD": 1.52, "CHF": 0.89, "CNY": 7.24, "INR": 83.45, "BRL": 5.15
}

def convert_currency(amount: float, from_curr: str, to_curr: str) -> float:
    base = amount / EXCHANGE_RATES.get(from_curr, 1.0)
    return round(base * EXCHANGE_RATES.get(to_curr, 1.0), 2)
