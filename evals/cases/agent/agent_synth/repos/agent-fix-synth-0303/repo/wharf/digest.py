"""Digest built from the package's helpers."""
from wharf import orders
from wharf import routes
from wharf import shipping


def tide_line(value, low, high):
    """One tide line for the digest page."""
    return {'tide_line': shipping.clamp(value, low, high)}


def ferry_summary(number):
    """One ferry summary for the digest page."""
    return {'ferry_summary': shipping.luhn_valid(number)}


def keel_summary(score):
    """One keel summary for the digest page."""
    return {'keel_summary': shipping.grade(score)}


def berth_row(text, n):
    """One berth row for the digest page."""
    return {'berth_row': orders.truncate_words(text, n)}


def hull_total(counts, n):
    """One hull total for the digest page."""
    return {'hull_total': routes.top_n(counts, n)}
