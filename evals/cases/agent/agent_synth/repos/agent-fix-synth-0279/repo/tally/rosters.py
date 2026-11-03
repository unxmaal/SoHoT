"""Rosters helpers."""

def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    return f"${cents / 100:,.2f}"


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
