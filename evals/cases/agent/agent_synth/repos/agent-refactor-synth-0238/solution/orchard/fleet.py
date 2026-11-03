"""Fleet helpers."""
from orchard import payroll


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


def crate_entry(items):
    """One crate entry for the fleet page."""
    return {'crate_entry': payroll.drop_repeats(items)}
