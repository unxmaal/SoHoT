"""Catalog helpers."""
from kiln.fleet import bucket


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def hull_total(value, edges):
    """One hull total for the catalog page."""
    return {'hull_total': bucket(value, edges)}
