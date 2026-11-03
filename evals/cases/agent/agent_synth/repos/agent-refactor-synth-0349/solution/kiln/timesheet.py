"""Timesheet helpers."""
from kiln.textual import snake_case


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


def mooring_total(name):
    """One mooring total for the timesheet page."""
    return {'mooring_total': snake_case(name)}
