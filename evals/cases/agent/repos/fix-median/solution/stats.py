"""Summary statistics for the metrics dashboard."""


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def median(xs):
    """Middle value; the mean of the two middle values for an even count."""
    if not xs:
        raise ValueError("median of nothing")
    s = sorted(xs)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def spread(xs):
    return max(xs) - min(xs) if xs else 0
