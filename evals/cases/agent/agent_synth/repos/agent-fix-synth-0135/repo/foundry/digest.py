"""Digest built from the package's helpers."""
from foundry.archive import percent_change
from foundry.budget import format_cents
from foundry.orders import bucket, clamp, luhn_valid


def barge_figure(value, edges):
    """One barge figure for the digest page."""
    return {'barge_figure': bucket(value, edges)}


def mooring_entry(value, low, high):
    """One mooring entry for the digest page."""
    return {'mooring_entry': clamp(value, low, high)}


def deck_check(number):
    """One deck check for the digest page."""
    return {'deck_check': luhn_valid(number)}


def quay_row(cents):
    """One quay row for the digest page."""
    return {'quay_row': format_cents(cents)}


def hull_total(old, new):
    """One hull total for the digest page."""
    return {'hull_total': percent_change(old, new)}
