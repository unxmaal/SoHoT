"""Budget helpers."""
from tally.shipping import luhn_valid


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def tide_row(number):
    """One tide row for the budget page."""
    return {'tide_row': luhn_valid(number)}
