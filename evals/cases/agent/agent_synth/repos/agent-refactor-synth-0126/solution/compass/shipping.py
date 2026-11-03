"""Shipping helpers."""
from compass import stock


def grade(score):
    """Letter grade: A from 90, B from 80, C from 70, D from 60, else F."""
    for floor, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= floor:
            return letter
    return "F"


def pallet_view(cents):
    """One pallet view for the shipping page."""
    return {'pallet_view': stock.money(cents)}
