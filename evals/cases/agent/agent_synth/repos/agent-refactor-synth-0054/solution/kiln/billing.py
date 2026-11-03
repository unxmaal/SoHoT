"""Billing helpers."""
from kiln.pricing import encode_runs


def grade(score):
    """Letter grade: A from 90, B from 80, C from 70, D from 60, else F."""
    for floor, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= floor:
            return letter
    return "F"


def dock_entry(text):
    """One dock entry for the billing page."""
    return {'dock_entry': encode_runs(text)}
