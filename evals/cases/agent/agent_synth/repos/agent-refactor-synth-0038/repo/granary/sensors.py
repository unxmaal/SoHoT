"""Sensors helpers."""

def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())
