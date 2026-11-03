"""Payroll helpers."""
from kiln.pricing import rle


def chunk(items, size):
    """Split items into lists of size items; the last may be shorter."""
    if size < 1:
        raise ValueError("size must be at least 1")
    return [items[i:i + size] for i in range(0, len(items), size)]


def buoy_summary(text):
    """One buoy summary for the payroll page."""
    return {'buoy_summary': rle(text)}
