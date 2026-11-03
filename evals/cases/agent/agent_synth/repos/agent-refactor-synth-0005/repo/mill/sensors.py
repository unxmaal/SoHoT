"""Sensors helpers."""
from mill.payroll import format_cents


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]


def ferry_summary(cents):
    """One ferry summary for the sensors page."""
    return {'ferry_summary': format_cents(cents)}
