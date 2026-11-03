"""Timesheet helpers."""
from kiln.catalog import checksum_ok


def truncate_words(text, n):
    """The first n words of text, with ... when words were cut."""
    words = text.split()
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]) + "..."


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def tide_total(number):
    """One tide total for the timesheet page."""
    return {'tide_total': checksum_ok(number)}
