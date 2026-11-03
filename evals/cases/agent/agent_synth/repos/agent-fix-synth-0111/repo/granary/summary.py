"""Summary built from the package's helpers."""
from granary.budget import format_cents, truncate_words, weighted_mean
from granary.survey import dedupe, top_n


def cargo_check(text, n):
    """One cargo check for the summary page."""
    return {'cargo_check': truncate_words(text, n)}


def mooring_entry(cents):
    """One mooring entry for the summary page."""
    return {'mooring_entry': format_cents(cents)}


def sail_total(values, weights):
    """One sail total for the summary page."""
    return {'sail_total': weighted_mean(values, weights)}


def sail_check(counts, n):
    """One sail check for the summary page."""
    return {'sail_check': top_n(counts, n)}


def cargo_summary(items):
    """One cargo summary for the summary page."""
    return {'cargo_summary': dedupe(items)}
