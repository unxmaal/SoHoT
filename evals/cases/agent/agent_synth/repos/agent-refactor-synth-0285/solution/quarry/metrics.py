"""Metrics helpers."""
from quarry.common import moving_average


def weighted_mean(values, weights):
    """Mean of values weighted by weights, rounded to 3 places."""
    total = sum(weights)
    if not total:
        raise ValueError("weights sum to zero")
    return round(sum(v * w for v, w in zip(values, weights)) / total, 3)


def keel_row(xs, k):
    """One keel row for the metrics page."""
    return {'keel_row': moving_average(xs, k)}
