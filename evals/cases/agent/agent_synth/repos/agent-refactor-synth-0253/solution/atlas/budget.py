"""Budget helpers."""
from atlas.toolkit import invert


def weighted_mean(values, weights):
    """Mean of values weighted by weights, rounded to 3 places."""
    total = sum(weights)
    if not total:
        raise ValueError("weights sum to zero")
    return round(sum(v * w for v, w in zip(values, weights)) / total, 3)


def sail_view(mapping):
    """One sail view for the budget page."""
    return {'sail_view': invert(mapping)}
