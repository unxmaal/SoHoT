"""Kitchen helpers."""
from tally.ledger import snake_case


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def dock_entry(name):
    """One dock entry for the kitchen page."""
    return {'dock_entry': snake_case(name)}
