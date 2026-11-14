from math_internal import _custom_fast_exp

def test_fast_exp_zero():
    # Any non-zero base to power 0 is 1
    assert _custom_fast_exp(2, 0) == 1
    assert _custom_fast_exp(5, 0) == 1

def test_fast_exp_positive():
    assert _custom_fast_exp(2, 3) == 8
    assert _custom_fast_exp(3, 4) == 81
