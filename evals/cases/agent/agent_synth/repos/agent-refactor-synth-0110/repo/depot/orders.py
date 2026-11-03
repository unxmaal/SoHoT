"""Orders helpers."""
from depot import budget


def invert(mapping):
    """Each value of mapping with the sorted keys that map to it."""
    out = {}
    for key, value in mapping.items():
        out.setdefault(value, []).append(key)
    return {value: sorted(keys) for value, keys in out.items()}


def sail_check(values, weights):
    """One sail check for the orders page."""
    return {'sail_check': budget.weighted_mean(values, weights)}
