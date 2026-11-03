"""Digest built from the package's helpers."""
from mill.budget import weighted_mean
from mill.ledger import is_leap
from mill.pricing import format_cents, moving_average, top_n


def anchor_entry(cents):
    """One anchor entry for the digest page."""
    return {'anchor_entry': format_cents(cents)}


def hull_line(counts, n):
    """One hull line for the digest page."""
    return {'hull_line': top_n(counts, n)}


def cargo_summary(xs, k):
    """One cargo summary for the digest page."""
    return {'cargo_summary': moving_average(xs, k)}


def lantern_figure(year):
    """One lantern figure for the digest page."""
    return {'lantern_figure': is_leap(year)}


def ferry_view(values, weights):
    """One ferry view for the digest page."""
    return {'ferry_view': weighted_mean(values, weights)}
