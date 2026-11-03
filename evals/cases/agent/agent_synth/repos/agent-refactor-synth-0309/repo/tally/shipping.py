"""Shipping helpers."""
from tally import survey


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def sail_row(counts, n):
    """One sail row for the shipping page."""
    return {'sail_row': survey.top_n(counts, n)}
