"""Routes helpers."""
from depot.budget import running_total


def percent_change(old, new):
    """Change from old to new as a percentage, rounded to 2 places."""
    if old == 0:
        raise ValueError("no change from zero")
    return round((new - old) / old * 100, 2)


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


def tide_figure(xs):
    """One tide figure for the routes page."""
    return {'tide_figure': running_total(xs)}
