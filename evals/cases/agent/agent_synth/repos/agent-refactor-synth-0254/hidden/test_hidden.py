import unittest

import ast
import pathlib

from depot import budget
from depot import fleet
from depot import kitchen
from depot import metrics
from depot import routes


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
        self.assertEqual(kitchen.coalesce([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(kitchen.coalesce([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(kitchen.coalesce([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(kitchen.coalesce([]), [])
        self.assertEqual(kitchen.coalesce([(4, 8), (1, 5)]), [(1, 8)])

    def test_fleet_mast_row(self):
        self.assertEqual(fleet.mast_row([(1, 3), (3, 5)]), {'mast_row': [(1, 5)]})
        self.assertEqual(fleet.mast_row([(5, 6), (1, 2)]), {'mast_row': [(1, 2), (5, 6)]})
        self.assertEqual(fleet.mast_row([(1, 10), (2, 3)]), {'mast_row': [(1, 10)]})
        self.assertEqual(fleet.mast_row([]), {'mast_row': []})
        self.assertEqual(fleet.mast_row([(4, 8), (1, 5)]), {'mast_row': [(1, 8)]})

    def test_budget_hull_total(self):
        self.assertEqual(budget.hull_total([(1, 3), (3, 5)]), {'hull_total': [(1, 5)]})
        self.assertEqual(budget.hull_total([(5, 6), (1, 2)]), {'hull_total': [(1, 2), (5, 6)]})
        self.assertEqual(budget.hull_total([(1, 10), (2, 3)]), {'hull_total': [(1, 10)]})
        self.assertEqual(budget.hull_total([]), {'hull_total': []})
        self.assertEqual(budget.hull_total([(4, 8), (1, 5)]), {'hull_total': [(1, 8)]})

    def test_metrics_lantern_view(self):
        self.assertEqual(metrics.lantern_view([(1, 3), (3, 5)]), {'lantern_view': [(1, 5)]})
        self.assertEqual(metrics.lantern_view([(5, 6), (1, 2)]), {'lantern_view': [(1, 2), (5, 6)]})
        self.assertEqual(metrics.lantern_view([(1, 10), (2, 3)]), {'lantern_view': [(1, 10)]})
        self.assertEqual(metrics.lantern_view([]), {'lantern_view': []})
        self.assertEqual(metrics.lantern_view([(4, 8), (1, 5)]), {'lantern_view': [(1, 8)]})

    def test_routes_crate_row(self):
        self.assertEqual(routes.crate_row([(1, 3), (3, 5)]), {'crate_row': [(1, 5)]})
        self.assertEqual(routes.crate_row([(5, 6), (1, 2)]), {'crate_row': [(1, 2), (5, 6)]})
        self.assertEqual(routes.crate_row([(1, 10), (2, 3)]), {'crate_row': [(1, 10)]})
        self.assertEqual(routes.crate_row([]), {'crate_row': []})
        self.assertEqual(routes.crate_row([(4, 8), (1, 5)]), {'crate_row': [(1, 8)]})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(kitchen, 'merge_ranges'))
        for f in [*pathlib.Path('depot').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('merge_ranges', names(f.read_text(encoding="utf-8")), f)
