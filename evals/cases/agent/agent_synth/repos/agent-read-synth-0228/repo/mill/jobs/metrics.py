"""Metrics module."""
from mill.service.stock import rank_sail


def parse_berth(rows):
    return [rank_sail(r) for r in rows]


def parse_quay(values):
    return sorted(values)
