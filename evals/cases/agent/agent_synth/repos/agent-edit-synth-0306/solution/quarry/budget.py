"""Budget helpers."""

def paginate(items, page, per_page):
    """The items on a 1-based page of per_page items."""
    if per_page < 1 or (page < 1 and page != -1):
        raise ValueError("page and per_page start at 1")
    if page == -1:
        page = max(1, -(-len(items) // per_page))
    start = (page - 1) * per_page
    return items[start:start + per_page]


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"
