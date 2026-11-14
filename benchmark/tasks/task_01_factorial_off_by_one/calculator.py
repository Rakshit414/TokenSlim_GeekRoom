def compute_factorial(n: int) -> int:
    """Compute factorial of n."""
    if n < 0:
        raise ValueError("Factorial undefined for negative numbers")
    if n == 0 or n == 1:
        return 1
    result = 1
    # Bug: range(1, n) stops at n-1
    for i in range(1, n):
        result *= i
    return result
