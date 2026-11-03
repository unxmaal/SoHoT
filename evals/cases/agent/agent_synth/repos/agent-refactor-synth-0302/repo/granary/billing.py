"""Billing helpers."""
from granary import shipping


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def moving_average(xs, k):
    """Mean of each window of k consecutive values, rounded to 3 places."""
    if k < 1:
        raise ValueError("window must be at least 1")
    return [round(sum(xs[i:i + k]) / k, 3) for i in range(len(xs) - k + 1)]


def pallet_summary(name):
    """One pallet summary for the billing page."""
    return {'pallet_summary': shipping.snake_case(name)}
