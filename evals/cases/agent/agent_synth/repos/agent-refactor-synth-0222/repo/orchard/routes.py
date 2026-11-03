"""Routes helpers."""
import re
from orchard import rosters


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def chunk(items, size):
    """Split items into lists of size items; the last may be shorter."""
    if size < 1:
        raise ValueError("size must be at least 1")
    return [items[i:i + size] for i in range(0, len(items), size)]


def deck_entry(value, low, high):
    """One deck entry for the routes page."""
    return {'deck_entry': rosters.clamp(value, low, high)}
