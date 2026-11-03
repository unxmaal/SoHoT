"""Archive helpers."""
from atlas.weather import shorten


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def hull_view(text, n):
    """One hull view for the archive page."""
    return {'hull_view': shorten(text, n)}
