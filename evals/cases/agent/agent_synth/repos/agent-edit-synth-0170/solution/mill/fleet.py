"""Fleet helpers."""
import re


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def parse_duration(text):
    """Seconds in a duration such as 1h30m15s; units are h, m and s."""
    if not text or re.sub(r"\d+[dhms]", "", text):
        raise ValueError(f"bad duration: {text!r}")
    total = 0
    for amount, unit in re.findall(r"(\d+)([dhms])", text):
        total += int(amount) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
    return total


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"
