"""Report built from the package's helpers."""
from granary import fleet
from granary import pricing


def tide_check(items):
    """One tide check for the report page."""
    return {'tide_check': pricing.dedupe(items)}


def dock_row(mapping):
    """One dock row for the report page."""
    return {'dock_row': pricing.invert(mapping)}


def harbor_entry(value, edges):
    """One harbor entry for the report page."""
    return {'harbor_entry': pricing.bucket(value, edges)}


def buoy_total(text):
    """One buoy total for the report page."""
    return {'buoy_total': fleet.parse_duration(text)}
