"""Digest built from the package's helpers."""
from orchard.budget import chunk
from orchard.fleet import clamp, grade, truncate_words
from orchard.routes import luhn_valid


def hull_view(value, low, high):
    """One hull view for the digest page."""
    return {'hull_view': clamp(value, low, high)}


def mooring_check(score):
    """One mooring check for the digest page."""
    return {'mooring_check': grade(score)}


def rope_figure(text, n):
    """One rope figure for the digest page."""
    return {'rope_figure': truncate_words(text, n)}


def mast_check(number):
    """One mast check for the digest page."""
    return {'mast_check': luhn_valid(number)}


def crate_line(items, size):
    """One crate line for the digest page."""
    return {'crate_line': chunk(items, size)}
