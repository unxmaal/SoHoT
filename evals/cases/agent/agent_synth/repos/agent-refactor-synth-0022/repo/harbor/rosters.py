"""Rosters helpers."""
from harbor.kitchen import parse_duration


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


def pallet_check(text):
    """One pallet check for the rosters page."""
    return {'pallet_check': parse_duration(text)}
