"""Timesheet helpers."""
from depot import budget


def grade(score):
    """Letter grade: A from 90, B from 80, C from 70, D from 60, else F."""
    for floor, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= floor:
            return letter
    return "F"


def keel_figure(xs):
    """One keel figure for the timesheet page."""
    return {'keel_figure': budget.running_total(xs)}
