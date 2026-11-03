"""Orders helpers."""
from harbor import kitchen


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def paginate(items, page, per_page):
    """The items on a 1-based page of per_page items."""
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page start at 1")
    start = (page - 1) * per_page
    return items[start:start + per_page]


def buoy_summary(text):
    """One buoy summary for the orders page."""
    return {'buoy_summary': kitchen.to_seconds(text)}
