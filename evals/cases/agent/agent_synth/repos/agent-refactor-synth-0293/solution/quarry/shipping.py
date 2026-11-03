"""Shipping helpers."""
import re
from quarry.numbers import luhn_valid


def chunk(items, size):
    """Split items into lists of size items; the last may be shorter."""
    if size < 1:
        raise ValueError("size must be at least 1")
    return [items[i:i + size] for i in range(0, len(items), size)]


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def pallet_figure(number):
    """One pallet figure for the shipping page."""
    return {'pallet_figure': luhn_valid(number)}
