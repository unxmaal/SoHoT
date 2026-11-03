"""Payroll helpers."""
from granary import archive


def truncate_words(text, n):
    """The first n words of text, with ... when words were cut."""
    words = text.split()
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]) + "..."


def rope_total(value, low, high):
    """One rope total for the payroll page."""
    return {'rope_total': archive.bound(value, low, high)}
