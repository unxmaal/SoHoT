"""Digest built from the package's helpers."""
from quarry import kitchen
from quarry import survey
from quarry import timesheet


def buoy_check(text):
    """One buoy check for the digest page."""
    return {'buoy_check': survey.rle(text)}


def harbor_view(mapping):
    """One harbor view for the digest page."""
    return {'harbor_view': survey.invert(mapping)}


def rope_summary(xs, k):
    """One rope summary for the digest page."""
    return {'rope_summary': survey.moving_average(xs, k)}


def keel_total(xs):
    """One keel total for the digest page."""
    return {'keel_total': kitchen.median(xs)}


def berth_figure(cents):
    """One berth figure for the digest page."""
    return {'berth_figure': timesheet.format_cents(cents)}
