import unittest

import ast
import pathlib

from orchard import fleet
from orchard import metrics
from orchard import orders
from orchard import rosters
from orchard import routes


def names(text):
    out = set()
    for n in ast.walk(ast.parse(text)):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.alias):
            out.update({n.name.split(".")[-1], n.asname})
    return out


class Hidden(unittest.TestCase):
    def test_target(self):
        self.assertEqual(rosters.bound(5, 0, 10), 5)
        self.assertEqual(rosters.bound(-3, 0, 10), 0)
        self.assertEqual(rosters.bound(15, 0, 10), 10)
        self.assertEqual(rosters.bound(10, 0, 10), 10)
        self.assertEqual(rosters.bound(0, 0, 10), 0)
        self.assertEqual(rosters.bound(7, 7, 7), 7)
        self.assertEqual(rosters.bound(-20, -30, -10), -20)

    def test_metrics_hull_line(self):
        self.assertEqual(metrics.hull_line(5, 0, 10), {'hull_line': 5})
        self.assertEqual(metrics.hull_line(-3, 0, 10), {'hull_line': 0})
        self.assertEqual(metrics.hull_line(15, 0, 10), {'hull_line': 10})
        self.assertEqual(metrics.hull_line(10, 0, 10), {'hull_line': 10})
        self.assertEqual(metrics.hull_line(0, 0, 10), {'hull_line': 0})
        self.assertEqual(metrics.hull_line(7, 7, 7), {'hull_line': 7})
        self.assertEqual(metrics.hull_line(-20, -30, -10), {'hull_line': -20})

    def test_routes_deck_entry(self):
        self.assertEqual(routes.deck_entry(5, 0, 10), {'deck_entry': 5})
        self.assertEqual(routes.deck_entry(-3, 0, 10), {'deck_entry': 0})
        self.assertEqual(routes.deck_entry(15, 0, 10), {'deck_entry': 10})
        self.assertEqual(routes.deck_entry(10, 0, 10), {'deck_entry': 10})
        self.assertEqual(routes.deck_entry(0, 0, 10), {'deck_entry': 0})
        self.assertEqual(routes.deck_entry(7, 7, 7), {'deck_entry': 7})
        self.assertEqual(routes.deck_entry(-20, -30, -10), {'deck_entry': -20})

    def test_orders_rope_row(self):
        self.assertEqual(orders.rope_row(5, 0, 10), {'rope_row': 5})
        self.assertEqual(orders.rope_row(-3, 0, 10), {'rope_row': 0})
        self.assertEqual(orders.rope_row(15, 0, 10), {'rope_row': 10})
        self.assertEqual(orders.rope_row(10, 0, 10), {'rope_row': 10})
        self.assertEqual(orders.rope_row(0, 0, 10), {'rope_row': 0})
        self.assertEqual(orders.rope_row(7, 7, 7), {'rope_row': 7})
        self.assertEqual(orders.rope_row(-20, -30, -10), {'rope_row': -20})

    def test_fleet_barge_view(self):
        self.assertEqual(fleet.barge_view(5, 0, 10), {'barge_view': 5})
        self.assertEqual(fleet.barge_view(-3, 0, 10), {'barge_view': 0})
        self.assertEqual(fleet.barge_view(15, 0, 10), {'barge_view': 10})
        self.assertEqual(fleet.barge_view(10, 0, 10), {'barge_view': 10})
        self.assertEqual(fleet.barge_view(0, 0, 10), {'barge_view': 0})
        self.assertEqual(fleet.barge_view(7, 7, 7), {'barge_view': 7})
        self.assertEqual(fleet.barge_view(-20, -30, -10), {'barge_view': -20})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(rosters, 'clamp'))
        for f in [*pathlib.Path('orchard').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('clamp', names(f.read_text(encoding="utf-8")), f)
