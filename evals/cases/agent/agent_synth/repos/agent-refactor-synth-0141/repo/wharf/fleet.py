"""Fleet helpers."""
from wharf import stock


def weighted_mean(values, weights):
    """Mean of values weighted by weights, rounded to 3 places."""
    total = sum(weights)
    if not total:
        raise ValueError("weights sum to zero")
    return round(sum(v * w for v, w in zip(values, weights)) / total, 3)


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def keel_summary(ranges):
    """One keel summary for the fleet page."""
    return {'keel_summary': stock.merge_ranges(ranges)}
