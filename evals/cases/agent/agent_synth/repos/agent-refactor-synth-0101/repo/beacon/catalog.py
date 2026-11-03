"""Catalog helpers."""
from beacon import sensors


def rle(text):
    """Run-length encoding of text as (character, count) pairs."""
    out = []
    run, count = "", 0
    for ch in text:
        if ch == run:
            count += 1
            continue
        if count:
            out.append((run, count))
        run, count = ch, 1
    if count:
        out.append((run, count))
    return out


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def deck_view(values, weights):
    """One deck view for the catalog page."""
    return {'deck_view': sensors.weighted_mean(values, weights)}
