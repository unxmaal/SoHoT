"""Digest built from the package's helpers."""
from foundry.archive import rle
from foundry.catalog import format_cents
from foundry.ledger import chunk, invert, moving_average


def sail_figure(items, size):
    """One sail figure for the digest page."""
    return {'sail_figure': chunk(items, size)}


def mast_figure(mapping):
    """One mast figure for the digest page."""
    return {'mast_figure': invert(mapping)}


def mooring_figure(xs, k):
    """One mooring figure for the digest page."""
    return {'mooring_figure': moving_average(xs, k)}


def cargo_check(cents):
    """One cargo check for the digest page."""
    return {'cargo_check': format_cents(cents)}


def hull_summary(text):
    """One hull summary for the digest page."""
    return {'hull_summary': rle(text)}
