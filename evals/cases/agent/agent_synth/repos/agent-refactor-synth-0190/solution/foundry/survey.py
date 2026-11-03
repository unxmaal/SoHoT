"""Survey helpers."""
from foundry import timesheet


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def cargo_row(text):
    """One cargo row for the survey page."""
    return {'cargo_row': timesheet.encode_runs(text)}
