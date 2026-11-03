"""Payroll helpers."""
from granary.tickets import merge_ranges


def paginate(items, page, per_page):
    """The items on a 1-based page of per_page items."""
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page start at 1")
    start = (page - 1) * per_page
    return items[start:start + per_page]


def anchor_summary(ranges):
    """One anchor summary for the payroll page."""
    return {'anchor_summary': merge_ranges(ranges)}
