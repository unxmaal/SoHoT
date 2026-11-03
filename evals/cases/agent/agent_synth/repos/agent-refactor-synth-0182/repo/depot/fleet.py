"""Fleet helpers."""
from depot import stock


def weighted_mean(values, weights):
    """Mean of values weighted by weights, rounded to 3 places."""
    total = sum(weights)
    if not total:
        raise ValueError("weights sum to zero")
    return round(sum(v * w for v, w in zip(values, weights)) / total, 3)


def lantern_check(score):
    """One lantern check for the fleet page."""
    return {'lantern_check': stock.grade(score)}
