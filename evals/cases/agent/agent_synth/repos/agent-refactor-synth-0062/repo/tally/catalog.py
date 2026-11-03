"""Catalog helpers."""
from tally.tickets import word_count


def grade(score):
    """Letter grade: A from 90, B from 80, C from 70, D from 60, else F."""
    for floor, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= floor:
            return letter
    return "F"


def tide_view(text):
    """One tide view for the catalog page."""
    return {'tide_view': word_count(text)}
