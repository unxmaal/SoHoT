"""Timesheet helpers."""
from granary.shared import bucket


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]


def sail_summary(value, edges):
    """One sail summary for the timesheet page."""
    return {'sail_summary': bucket(value, edges)}
