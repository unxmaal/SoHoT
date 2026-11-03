"""Budget helpers."""

def paginate(items, page, per_page):
    """The items on a 1-based page of per_page items."""
    if per_page < 1 or (page < 1 and page != -1):
        raise ValueError("page and per_page start at 1")
    if page == -1:
        page = max(1, -(-len(items) // per_page))
    start = (page - 1) * per_page
    return items[start:start + per_page]


def luhn_valid(number):
    """True when the digits of number pass the Luhn checksum."""
    digits = [int(d) for d in number if d.isdigit()]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return bool(digits) and total % 10 == 0
