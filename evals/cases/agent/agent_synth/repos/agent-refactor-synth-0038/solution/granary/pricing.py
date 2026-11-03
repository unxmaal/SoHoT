"""Pricing helpers."""
import re
from granary import sensors


def parse_duration(text):
    """Seconds in a duration such as 1h30m15s; units are h, m and s."""
    if not text or re.sub(r"\d+[hms]", "", text):
        raise ValueError(f"bad duration: {text!r}")
    total = 0
    for amount, unit in re.findall(r"(\d+)([hms])", text):
        total += int(amount) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def sail_check(text):
    """One sail check for the pricing page."""
    return {'sail_check': sensors.words_in(text)}
