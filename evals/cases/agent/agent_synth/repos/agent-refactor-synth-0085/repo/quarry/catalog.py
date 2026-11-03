"""Catalog helpers."""
import re
from quarry.routes import luhn_valid


def parse_duration(text):
    """Seconds in a duration such as 1h30m15s; units are h, m and s."""
    if not text or re.sub(r"\d+[hms]", "", text):
        raise ValueError(f"bad duration: {text!r}")
    total = 0
    for amount, unit in re.findall(r"(\d+)([hms])", text):
        total += int(amount) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def mast_entry(number):
    """One mast entry for the catalog page."""
    return {'mast_entry': luhn_valid(number)}
