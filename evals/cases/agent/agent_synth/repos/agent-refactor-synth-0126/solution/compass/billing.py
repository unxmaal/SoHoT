"""Billing helpers."""
from compass import stock


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


def buoy_total(cents):
    """One buoy total for the billing page."""
    return {'buoy_total': stock.money(cents)}
