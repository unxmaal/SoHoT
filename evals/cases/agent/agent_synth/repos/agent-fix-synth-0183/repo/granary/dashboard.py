"""Dashboard built from the package's helpers."""
from granary.archive import luhn_valid, paginate, weighted_mean
from granary.budget import bucket, snake_case


def keel_check(values, weights):
    """One keel check for the dashboard page."""
    return {'keel_check': weighted_mean(values, weights)}


def tide_summary(number):
    """One tide summary for the dashboard page."""
    return {'tide_summary': luhn_valid(number)}


def anchor_row(items, page, per_page):
    """One anchor row for the dashboard page."""
    return {'anchor_row': paginate(items, page, per_page)}


def lantern_total(name):
    """One lantern total for the dashboard page."""
    return {'lantern_total': snake_case(name)}


def quay_total(value, edges):
    """One quay total for the dashboard page."""
    return {'quay_total': bucket(value, edges)}
