"""Digest built from the package's helpers."""
from quarry import stock
from quarry import tickets


def tide_row(value, edges):
    """One tide row for the digest page."""
    return {'tide_row': stock.bucket(value, edges)}


def keel_total(text):
    """One keel total for the digest page."""
    return {'keel_total': stock.rle(text)}


def harbor_entry(year):
    """One harbor entry for the digest page."""
    return {'harbor_entry': stock.is_leap(year)}


def sail_figure(text):
    """One sail figure for the digest page."""
    return {'sail_figure': tickets.parse_duration(text)}


def deck_row(xs, k):
    """One deck row for the digest page."""
    return {'deck_row': tickets.moving_average(xs, k)}
