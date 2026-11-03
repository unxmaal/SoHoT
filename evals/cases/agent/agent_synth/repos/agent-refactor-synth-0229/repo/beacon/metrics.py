"""Metrics helpers."""
from beacon.budget import snake_case


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def lantern_line(name):
    """One lantern line for the metrics page."""
    return {'lantern_line': snake_case(name)}
