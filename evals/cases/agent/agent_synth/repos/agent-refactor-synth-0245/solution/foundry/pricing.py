"""Pricing helpers."""
from foundry import tools


def paginate(items, page, per_page):
    """The items on a 1-based page of per_page items."""
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page start at 1")
    start = (page - 1) * per_page
    return items[start:start + per_page]


def sail_total(value, edges):
    """One sail total for the pricing page."""
    return {'sail_total': tools.bucket(value, edges)}
