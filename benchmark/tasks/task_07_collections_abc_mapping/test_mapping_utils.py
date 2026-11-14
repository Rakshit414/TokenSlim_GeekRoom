import pytest

def test_is_mapping_type():
    from mapping_utils import is_mapping_type
    assert is_mapping_type({"a": 1}) is True
    assert is_mapping_type([1, 2, 3]) is False
