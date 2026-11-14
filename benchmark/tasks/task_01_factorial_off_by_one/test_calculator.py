from calculator import compute_factorial

def test_factorial_zero():
    assert compute_factorial(0) == 1

def test_factorial_one():
    assert compute_factorial(1) == 1

def test_factorial_five():
    # 5! = 120
    assert compute_factorial(5) == 120
