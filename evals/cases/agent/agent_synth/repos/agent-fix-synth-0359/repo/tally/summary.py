"""Summary built from the package's helpers."""
from tally.archive import bucket, rle
from tally.orders import luhn_valid
from tally.shipping import running_total, weighted_mean


def anchor_check(value, edges):
    """One anchor check for the summary page."""
    return {'anchor_check': bucket(value, edges)}


def sail_summary(text):
    """One sail summary for the summary page."""
    return {'sail_summary': rle(text)}


def rope_entry(xs):
    """One rope entry for the summary page."""
    return {'rope_entry': running_total(xs)}


def ferry_line(values, weights):
    """One ferry line for the summary page."""
    return {'ferry_line': weighted_mean(values, weights)}


def cargo_entry(number):
    """One cargo entry for the summary page."""
    return {'cargo_entry': luhn_valid(number)}
