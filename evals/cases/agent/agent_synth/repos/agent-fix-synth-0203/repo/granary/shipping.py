"""Shipping helpers."""

def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())
