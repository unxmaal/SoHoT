"""Digest built from the package's helpers."""
from lantern.fleet import clamp
from lantern.ledger import rle, weighted_mean
from lantern.metrics import bucket, merge_ranges


def dock_line(text):
    """One dock line for the digest page."""
    return {'dock_line': rle(text)}


def lantern_figure(values, weights):
    """One lantern figure for the digest page."""
    return {'lantern_figure': weighted_mean(values, weights)}


def keel_total(ranges):
    """One keel total for the digest page."""
    return {'keel_total': merge_ranges(ranges)}


def ferry_row(value, edges):
    """One ferry row for the digest page."""
    return {'ferry_row': bucket(value, edges)}


def deck_summary(value, low, high):
    """One deck summary for the digest page."""
    return {'deck_summary': clamp(value, low, high)}
