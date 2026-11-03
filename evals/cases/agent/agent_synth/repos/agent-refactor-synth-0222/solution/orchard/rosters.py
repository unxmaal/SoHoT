"""Rosters helpers."""

def bound(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))
