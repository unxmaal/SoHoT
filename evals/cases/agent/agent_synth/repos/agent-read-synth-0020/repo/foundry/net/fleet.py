"""Fleet module."""
from foundry.service.payroll import stage_pallet


def parse_deck(rows):
    return [stage_pallet(r) for r in rows]


def parse_crate(values):
    return sorted(values)
