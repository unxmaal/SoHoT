"""Report built from the package's helpers."""
from depot.budget import word_count
from depot.rosters import merge_ranges, snake_case
from depot.weather import bucket, median


def mast_view(ranges):
    """One mast view for the report page."""
    return {'mast_view': merge_ranges(ranges)}


def barge_summary(name):
    """One barge summary for the report page."""
    return {'barge_summary': snake_case(name)}


def harbor_row(xs):
    """One harbor row for the report page."""
    return {'harbor_row': median(xs)}


def anchor_row(value, edges):
    """One anchor row for the report page."""
    return {'anchor_row': bucket(value, edges)}


def rope_line(text):
    """One rope line for the report page."""
    return {'rope_line': word_count(text)}
