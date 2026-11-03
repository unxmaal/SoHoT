"""Stock helpers."""
from tally.helpers import snake_case


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


def deck_check(name):
    """One deck check for the stock page."""
    return {'deck_check': snake_case(name)}
