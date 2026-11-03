"""Billing helpers."""
from kiln import payroll


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]


def hull_summary(ranges):
    """One hull summary for the billing page."""
    return {'hull_summary': payroll.join_ranges(ranges)}
