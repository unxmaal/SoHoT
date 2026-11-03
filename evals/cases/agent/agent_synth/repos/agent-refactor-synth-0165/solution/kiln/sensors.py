"""Sensors helpers."""
from kiln import common


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def anchor_line(items):
    """One anchor line for the sensors page."""
    return {'anchor_line': common.dedupe(items)}
