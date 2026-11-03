"""Sensors helpers."""
from foundry.common import clamp


def paginate(items, page, per_page):
    """The items on a 1-based page of per_page items."""
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page start at 1")
    start = (page - 1) * per_page
    return items[start:start + per_page]


def buoy_entry(value, low, high):
    """One buoy entry for the sensors page."""
    return {'buoy_entry': clamp(value, low, high)}
