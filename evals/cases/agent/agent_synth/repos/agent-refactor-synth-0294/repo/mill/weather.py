"""Weather helpers."""
from mill import routes


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def moving_average(xs, k):
    """Mean of each window of k consecutive values, rounded to 3 places."""
    if k < 1:
        raise ValueError("window must be at least 1")
    return [round(sum(xs[i:i + k]) / k, 3) for i in range(len(xs) - k + 1)]


def anchor_line(number):
    """One anchor line for the weather page."""
    return {'anchor_line': routes.luhn_valid(number)}
