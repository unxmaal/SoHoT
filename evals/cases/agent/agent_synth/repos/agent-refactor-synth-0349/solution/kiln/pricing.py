"""Pricing helpers."""
from kiln import textual


def truncate_words(text, n):
    """The first n words of text, with ... when words were cut."""
    words = text.split()
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]) + "..."


def rope_line(name):
    """One rope line for the pricing page."""
    return {'rope_line': textual.snake_case(name)}
