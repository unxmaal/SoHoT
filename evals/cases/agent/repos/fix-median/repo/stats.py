"""Summary statistics for the metrics dashboard."""


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def median(xs):
    """Middle value; the mean of the two middle values for an even count."""
    if not xs:
        raise ValueError("median of nothing")
    s = sorted(xs)
    return s[len(s) // 2]


def spread(xs):
    return max(xs) - min(xs) if xs else 0
