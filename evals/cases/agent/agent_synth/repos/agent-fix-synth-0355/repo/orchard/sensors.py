"""Sensors helpers."""

def truncate_words(text, n):
    """The first n words of text, with ... when words were cut."""
    words = text.split()
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]) + "..."


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]
