"""Sensors helpers."""
from atlas.ledger import mark_of


def weighted_mean(values, weights):
    """Mean of values weighted by weights, rounded to 3 places."""
    total = sum(weights)
    if not total:
        raise ValueError("weights sum to zero")
    return round(sum(v * w for v, w in zip(values, weights)) / total, 3)


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def pallet_total(score):
    """One pallet total for the sensors page."""
    return {'pallet_total': mark_of(score)}
