"""Tickets helpers."""
import re


def bucket(value, edges, labels=None):
    """How many of the sorted edges value has reached."""
    index = sum(1 for edge in edges if value >= edge)
    return index if labels is None else labels[index]


def parse_duration(text):
    """Seconds in a duration such as 1h30m15s; units are h, m and s."""
    if not text or re.sub(r"\d+[hms]", "", text):
        raise ValueError(f"bad duration: {text!r}")
    total = 0
    for amount, unit in re.findall(r"(\d+)([hms])", text):
        total += int(amount) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total
