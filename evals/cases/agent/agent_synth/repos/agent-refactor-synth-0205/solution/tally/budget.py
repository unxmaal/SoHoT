"""Budget helpers."""
from tally.common import bucket


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


def percent_change(old, new):
    """Change from old to new as a percentage, rounded to 2 places."""
    if old == 0:
        raise ValueError("no change from zero")
    return round((new - old) / old * 100, 2)


def rope_row(value, edges):
    """One rope row for the budget page."""
    return {'rope_row': bucket(value, edges)}
