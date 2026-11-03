"""Payroll helpers."""
from kiln import archive


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def mast_view(text, n):
    """One mast view for the payroll page."""
    return {'mast_view': archive.first_words(text, n)}
