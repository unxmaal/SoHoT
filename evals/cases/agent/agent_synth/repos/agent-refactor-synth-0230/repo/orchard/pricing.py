"""Pricing helpers."""
from orchard import orders


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


def anchor_figure(year):
    """One anchor figure for the pricing page."""
    return {'anchor_figure': orders.is_leap(year)}
