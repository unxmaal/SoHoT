"""Report built from the package's helpers."""
from mill.billing import invert, running_total
from mill.sensors import merge_ranges, snake_case
from mill.survey import bucket


def ferry_entry(name):
    """One ferry entry for the report page."""
    return {'ferry_entry': snake_case(name)}


def mast_figure(ranges):
    """One mast figure for the report page."""
    return {'mast_figure': merge_ranges(ranges)}


def dock_check(xs):
    """One dock check for the report page."""
    return {'dock_check': running_total(xs)}


def quay_line(mapping):
    """One quay line for the report page."""
    return {'quay_line': invert(mapping)}


def crate_check(value, edges):
    """One crate check for the report page."""
    return {'crate_check': bucket(value, edges)}
