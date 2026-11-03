"""Metrics helpers."""
from depot.budget import weighted_mean


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def berth_row(values, weights):
    """One berth row for the metrics page."""
    return {'berth_row': weighted_mean(values, weights)}
