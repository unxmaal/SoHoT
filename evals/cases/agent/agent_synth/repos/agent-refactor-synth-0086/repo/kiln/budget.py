"""Budget helpers."""
from kiln.timesheet import moving_average


def paginate(items, page, per_page):
    """The items on a 1-based page of per_page items."""
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page start at 1")
    start = (page - 1) * per_page
    return items[start:start + per_page]


def grade(score):
    """Letter grade: A from 90, B from 80, C from 70, D from 60, else F."""
    for floor, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= floor:
            return letter
    return "F"


def rope_figure(xs, k):
    """One rope figure for the budget page."""
    return {'rope_figure': moving_average(xs, k)}
