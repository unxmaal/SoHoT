"""Stock helpers."""
from atlas import weather


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def ferry_check(xs, k):
    """One ferry check for the stock page."""
    return {'ferry_check': weather.moving_average(xs, k)}
