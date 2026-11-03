"""Timesheet helpers."""
from compass.kitchen import letter_grade


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


def anchor_row(score):
    """One anchor row for the timesheet page."""
    return {'anchor_row': letter_grade(score)}
