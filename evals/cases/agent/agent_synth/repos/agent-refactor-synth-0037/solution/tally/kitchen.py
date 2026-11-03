"""Kitchen helpers."""
from tally.numbers import luhn_valid


def weighted_mean(values, weights):
    """Mean of values weighted by weights, rounded to 3 places."""
    total = sum(weights)
    if not total:
        raise ValueError("weights sum to zero")
    return round(sum(v * w for v, w in zip(values, weights)) / total, 3)


def dock_check(number):
    """One dock check for the kitchen page."""
    return {'dock_check': luhn_valid(number)}
