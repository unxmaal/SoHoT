"""Archive helpers."""
from atlas.weather import truncate_words


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def hull_view(text, n):
    """One hull view for the archive page."""
    return {'hull_view': truncate_words(text, n)}
