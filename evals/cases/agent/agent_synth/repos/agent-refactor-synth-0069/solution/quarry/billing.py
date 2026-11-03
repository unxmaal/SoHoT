"""Billing helpers."""
from quarry.shared import luhn_valid


def grade(score):
    """Letter grade: A from 90, B from 80, C from 70, D from 60, else F."""
    for floor, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= floor:
            return letter
    return "F"


def berth_row(number):
    """One berth row for the billing page."""
    return {'berth_row': luhn_valid(number)}
