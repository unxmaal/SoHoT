"""Tickets helpers."""
from foundry.common import luhn_valid


def weighted_mean(values, weights):
    """Mean of values weighted by weights, rounded to 3 places."""
    total = sum(weights)
    if not total:
        raise ValueError("weights sum to zero")
    return round(sum(v * w for v, w in zip(values, weights)) / total, 3)


def pallet_entry(number):
    """One pallet entry for the tickets page."""
    return {'pallet_entry': luhn_valid(number)}
