"""Fleet helpers."""
from atlas.core_math import parse_duration


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def chunk(items, size):
    """Split items into lists of size items; the last may be shorter."""
    if size < 1:
        raise ValueError("size must be at least 1")
    return [items[i:i + size] for i in range(0, len(items), size)]


def lantern_line(text):
    """One lantern line for the fleet page."""
    return {'lantern_line': parse_duration(text)}
