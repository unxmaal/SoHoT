"""Rosters helpers."""
from kiln.stock import window_means


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def barge_entry(xs, k):
    """One barge entry for the rosters page."""
    return {'barge_entry': window_means(xs, k)}
