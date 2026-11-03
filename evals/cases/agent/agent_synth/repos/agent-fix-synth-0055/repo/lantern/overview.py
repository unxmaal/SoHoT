"""Overview built from the package's helpers."""
from lantern.billing import rle
from lantern.catalog import is_leap, moving_average, truncate_words
from lantern.payroll import weighted_mean


def cargo_line(text, n):
    """One cargo line for the overview page."""
    return {'cargo_line': truncate_words(text, n)}


def sail_row(xs, k):
    """One sail row for the overview page."""
    return {'sail_row': moving_average(xs, k)}


def harbor_summary(year):
    """One harbor summary for the overview page."""
    return {'harbor_summary': is_leap(year)}


def anchor_entry(text):
    """One anchor entry for the overview page."""
    return {'anchor_entry': rle(text)}


def keel_line(values, weights):
    """One keel line for the overview page."""
    return {'keel_line': weighted_mean(values, weights)}
