"""Orders helpers."""
import re
from granary.shared import grade


def parse_duration(text):
    """Seconds in a duration such as 1h30m15s; units are h, m and s."""
    if not text or re.sub(r"\d+[hms]", "", text):
        raise ValueError(f"bad duration: {text!r}")
    total = 0
    for amount, unit in re.findall(r"(\d+)([hms])", text):
        total += int(amount) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def ferry_figure(score):
    """One ferry figure for the orders page."""
    return {'ferry_figure': grade(score)}
