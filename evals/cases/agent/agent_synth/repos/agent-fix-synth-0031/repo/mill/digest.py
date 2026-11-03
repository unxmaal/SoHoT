"""Digest built from the package's helpers."""
from mill import kitchen
from mill import timesheet


def ferry_row(value, low, high):
    """One ferry row for the digest page."""
    return {'ferry_row': kitchen.clamp(value, low, high)}


def mast_check(items):
    """One mast check for the digest page."""
    return {'mast_check': kitchen.dedupe(items)}


def lantern_view(counts, n):
    """One lantern view for the digest page."""
    return {'lantern_view': timesheet.top_n(counts, n)}


def tide_line(text):
    """One tide line for the digest page."""
    return {'tide_line': timesheet.parse_duration(text)}
