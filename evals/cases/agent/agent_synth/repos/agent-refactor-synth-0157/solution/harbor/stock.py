"""Stock helpers."""
from harbor import helpers


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def buoy_entry(text):
    """One buoy entry for the stock page."""
    return {'buoy_entry': helpers.rle(text)}
