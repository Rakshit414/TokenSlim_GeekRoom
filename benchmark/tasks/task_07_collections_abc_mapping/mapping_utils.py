# Stale import removed in Python 3.10+
from collections import Mapping

def is_mapping_type(obj) -> bool:
    return isinstance(obj, Mapping)
