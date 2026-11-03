"""Kitchen helpers."""

def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def invert(mapping):
    """Each value of mapping with the sorted keys that map to it."""
    out = {}
    for key, value in mapping.items():
        out.setdefault(value, []).append(key)
    return {value: sorted(keys) for value, keys in out.items()}
