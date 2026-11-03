"""Archive helpers."""
from kiln import common


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def truncate_words(text, n):
    """The first n words of text, with ... when words were cut."""
    words = text.split()
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]) + "..."


def mooring_figure(items):
    """One mooring figure for the archive page."""
    return {'mooring_figure': common.dedupe(items)}
