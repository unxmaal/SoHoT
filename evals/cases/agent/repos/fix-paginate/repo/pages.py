"""Pagination for list endpoints. Pages are numbered from 1."""


def page_count(total, per_page):
    return (total + per_page - 1) // per_page


def paginate(items, page, per_page=10):
    """The items on `page` (1-based). An out-of-range page is empty."""
    if page < 1:
        raise ValueError("pages start at 1")
    start = page * per_page
    return items[start:start + per_page]
