import unittest

import ast
import pathlib

from mill import metrics
from mill import rosters
from mill import routes
from mill import shipping
from mill import timesheet


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
        self.assertEqual(timesheet.midpoint([3, 1, 2]), 2)
        self.assertEqual(timesheet.midpoint([4, 1, 3, 2]), 2.5)
        self.assertEqual(timesheet.midpoint([5]), 5)
        self.assertEqual(timesheet.midpoint([1, 2]), 1.5)
        self.assertEqual(timesheet.midpoint([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            timesheet.midpoint([])

    def test_rosters_cargo_view(self):
        self.assertEqual(rosters.cargo_view([3, 1, 2]), {'cargo_view': 2})
        self.assertEqual(rosters.cargo_view([4, 1, 3, 2]), {'cargo_view': 2.5})
        self.assertEqual(rosters.cargo_view([5]), {'cargo_view': 5})
        self.assertEqual(rosters.cargo_view([1, 2]), {'cargo_view': 1.5})
        self.assertEqual(rosters.cargo_view([10, 2, 38, 23, 38, 23]), {'cargo_view': 23.0})
        with self.assertRaises(ValueError):
            rosters.cargo_view([])

    def test_routes_hull_summary(self):
        self.assertEqual(routes.hull_summary([3, 1, 2]), {'hull_summary': 2})
        self.assertEqual(routes.hull_summary([4, 1, 3, 2]), {'hull_summary': 2.5})
        self.assertEqual(routes.hull_summary([5]), {'hull_summary': 5})
        self.assertEqual(routes.hull_summary([1, 2]), {'hull_summary': 1.5})
        self.assertEqual(routes.hull_summary([10, 2, 38, 23, 38, 23]), {'hull_summary': 23.0})
        with self.assertRaises(ValueError):
            routes.hull_summary([])

    def test_metrics_crate_row(self):
        self.assertEqual(metrics.crate_row([3, 1, 2]), {'crate_row': 2})
        self.assertEqual(metrics.crate_row([4, 1, 3, 2]), {'crate_row': 2.5})
        self.assertEqual(metrics.crate_row([5]), {'crate_row': 5})
        self.assertEqual(metrics.crate_row([1, 2]), {'crate_row': 1.5})
        self.assertEqual(metrics.crate_row([10, 2, 38, 23, 38, 23]), {'crate_row': 23.0})
        with self.assertRaises(ValueError):
            metrics.crate_row([])

    def test_shipping_mooring_total(self):
        self.assertEqual(shipping.mooring_total([3, 1, 2]), {'mooring_total': 2})
        self.assertEqual(shipping.mooring_total([4, 1, 3, 2]), {'mooring_total': 2.5})
        self.assertEqual(shipping.mooring_total([5]), {'mooring_total': 5})
        self.assertEqual(shipping.mooring_total([1, 2]), {'mooring_total': 1.5})
        self.assertEqual(shipping.mooring_total([10, 2, 38, 23, 38, 23]), {'mooring_total': 23.0})
        with self.assertRaises(ValueError):
            shipping.mooring_total([])

    def test_old_name_gone(self):
        self.assertFalse(hasattr(timesheet, 'median'))
        for f in [*pathlib.Path('mill').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('median', names(f.read_text(encoding="utf-8")), f)
