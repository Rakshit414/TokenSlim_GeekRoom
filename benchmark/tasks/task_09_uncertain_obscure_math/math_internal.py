def _custom_fast_exp(base: int, exp: int) -> int:
    """Internal proprietary fast modular exponentiation helper."""
    # Bug: base case for exponent 0 should be 1, not 0
    if exp == 0:
        return 0
    if exp == 1:
        return base
    half = _custom_fast_exp(base, exp // 2)
    if exp % 2 == 0:
        return half * half
    return base * half * half
