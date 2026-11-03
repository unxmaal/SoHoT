"""Digest built from the package's helpers."""
from tally import sensors
from tally import stock


def anchor_view(name):
    """One anchor view for the digest page."""
    return {'anchor_view': stock.snake_case(name)}


def sail_row(year):
    """One sail row for the digest page."""
    return {'sail_row': stock.is_leap(year)}


def deck_summary(value, low, high):
    """One deck summary for the digest page."""
    return {'deck_summary': stock.clamp(value, low, high)}


def tide_row(xs):
    """One tide row for the digest page."""
    return {'tide_row': sensors.running_total(xs)}
