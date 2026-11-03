"""Archive helpers."""
from meadow import billing


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def buoy_view(value, edges):
    """One buoy view for the archive page."""
    return {'buoy_view': billing.bucket(value, edges)}
