"""Totals over the order export."""
import csv
from pathlib import Path

from foundry.pricing import line

COUNTED = ('ok',)
ORDERS = Path(__file__).resolve().parent.parent / "data" / "orders.csv"


def rows():
    with open(ORDERS, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def grand_total():
    return sum(line(int(r["qty"]), int(r["cents"]), r["region"])
               for r in rows() if r["status"] in COUNTED)
