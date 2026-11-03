"""Budget helpers."""
from depot import kitchen


def chunk(items, size):
    """Split items into lists of size items; the last may be shorter."""
    if size < 1:
        raise ValueError("size must be at least 1")
    return [items[i:i + size] for i in range(0, len(items), size)]


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def hull_total(ranges):
    """One hull total for the budget page."""
    return {'hull_total': kitchen.merge_ranges(ranges)}
