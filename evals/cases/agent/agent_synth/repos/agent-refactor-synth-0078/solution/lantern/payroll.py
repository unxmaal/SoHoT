"""Payroll helpers."""
from lantern.routes import window_means


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


def sail_entry(xs, k):
    """One sail entry for the payroll page."""
    return {'sail_entry': window_means(xs, k)}
