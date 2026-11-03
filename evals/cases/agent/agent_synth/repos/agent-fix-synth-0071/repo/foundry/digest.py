"""Digest built from the package's helpers."""
from foundry.rosters import weighted_mean
from foundry.timesheet import dedupe, median, running_total


def berth_summary(xs):
    """One berth summary for the digest page."""
    return {'berth_summary': median(xs)}


def sail_entry(items):
    """One sail entry for the digest page."""
    return {'sail_entry': dedupe(items)}


def rope_check(xs):
    """One rope check for the digest page."""
    return {'rope_check': running_total(xs)}


def tide_row(values, weights):
    """One tide row for the digest page."""
    return {'tide_row': weighted_mean(values, weights)}
