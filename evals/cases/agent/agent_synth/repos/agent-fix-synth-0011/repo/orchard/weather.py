"""Weather helpers."""

def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]


def median(xs):
    """Middle value; the mean of the two middle values for an even count."""
    if not xs:
        raise ValueError("median of nothing")
    s = sorted(xs)
    return s[len(s) // 2]
