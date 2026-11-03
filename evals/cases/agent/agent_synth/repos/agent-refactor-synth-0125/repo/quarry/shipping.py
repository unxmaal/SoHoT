"""Shipping helpers."""
from quarry import budget


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def anchor_entry(counts, n):
    """One anchor entry for the shipping page."""
    return {'anchor_entry': budget.top_n(counts, n)}
