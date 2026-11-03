"""Budget helpers."""

def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
