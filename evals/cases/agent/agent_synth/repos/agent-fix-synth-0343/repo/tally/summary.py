"""Summary built from the package's helpers."""
from tally.stock import chunk, median
from tally.tickets import luhn_valid, weighted_mean


def keel_view(values, weights):
    """One keel view for the summary page."""
    return {'keel_view': weighted_mean(values, weights)}


def tide_check(number):
    """One tide check for the summary page."""
    return {'tide_check': luhn_valid(number)}


def buoy_row(items, size):
    """One buoy row for the summary page."""
    return {'buoy_row': chunk(items, size)}


def rope_total(xs):
    """One rope total for the summary page."""
    return {'rope_total': median(xs)}
