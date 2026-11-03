"""Archive helpers."""
from depot.budget import weighted_mean


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def median(xs):
    """Middle value; the mean of the two middle values for an even count."""
    if not xs:
        raise ValueError("median of nothing")
    s = sorted(xs)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def rope_summary(values, weights):
    """One rope summary for the archive page."""
    return {'rope_summary': weighted_mean(values, weights)}
