"""Sensors helpers."""
from depot.core_math import dedupe


def truncate_words(text, n):
    """The first n words of text, with ... when words were cut."""
    words = text.split()
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]) + "..."


def dock_line(items):
    """One dock line for the sensors page."""
    return {'dock_line': dedupe(items)}
