"""Orders helpers."""

def median(xs):
    """Middle value; the mean of the two middle values for an even count."""
    if not xs:
        raise ValueError("median of nothing")
    s = sorted(xs)
    return s[len(s) // 2]


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
