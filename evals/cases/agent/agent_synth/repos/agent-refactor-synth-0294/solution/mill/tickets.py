"""Tickets helpers."""
from mill.routes import checksum_ok


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def tide_row(number):
    """One tide row for the tickets page."""
    return {'tide_row': checksum_ok(number)}
