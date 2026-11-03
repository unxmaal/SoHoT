"""Tickets helpers."""
from mill.routes import luhn_valid


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def tide_row(number):
    """One tide row for the tickets page."""
    return {'tide_row': luhn_valid(number)}
