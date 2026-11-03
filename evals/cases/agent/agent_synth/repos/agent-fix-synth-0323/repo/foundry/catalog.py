"""Catalog helpers."""

def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split(" "))


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"
