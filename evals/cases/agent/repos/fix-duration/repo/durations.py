"""Parse human durations like '1h30m', '45s' or '2h' into seconds."""
import re

UNITS = {"h": 3600, "m": 60, "s": 1}
_PART = re.compile(r"(\d+)([hms])")


def parse_duration(text):
    text = text.strip().lower()
    if not text:
        raise ValueError("empty duration")
    m = _PART.match(text)
    if not m or m.end() != len(text):
        raise ValueError(f"bad duration: {text!r}")
    return int(m.group(1)) * UNITS[m.group(2)]
