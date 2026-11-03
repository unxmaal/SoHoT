"""Archive helpers."""
from foundry import rosters


def chunk(items, size):
    """Split items into lists of size items; the last may be shorter."""
    if size < 1:
        raise ValueError("size must be at least 1")
    return [items[i:i + size] for i in range(0, len(items), size)]


def tide_line(value, low, high):
    """One tide line for the archive page."""
    return {'tide_line': rosters.clamp(value, low, high)}
