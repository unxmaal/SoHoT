"""Weather helpers."""
from wharf.tools import percent_change


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def pallet_row(old, new):
    """One pallet row for the weather page."""
    return {'pallet_row': percent_change(old, new)}
