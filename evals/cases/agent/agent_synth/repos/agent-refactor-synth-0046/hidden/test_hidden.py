import unittest

import ast
import pathlib

from kiln import metrics
from kiln import payroll
from kiln import rosters
from kiln import routes


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
        self.assertEqual(routes.window_means([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(routes.window_means([5], 1), [5.0])
        self.assertEqual(routes.window_means([1, 2, 3], 3), [2.0])
        self.assertEqual(routes.window_means([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            routes.window_means([1, 2], 0)

    def test_metrics_berth_total(self):
        self.assertEqual(metrics.berth_total([1, 2, 3, 4], 2), {'berth_total': [1.5, 2.5, 3.5]})
        self.assertEqual(metrics.berth_total([5], 1), {'berth_total': [5.0]})
        self.assertEqual(metrics.berth_total([1, 2, 3], 3), {'berth_total': [2.0]})
        self.assertEqual(metrics.berth_total([2, 4, 6, 8, 10], 3), {'berth_total': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            metrics.berth_total([1, 2], 0)

    def test_payroll_tide_check(self):
        self.assertEqual(payroll.tide_check([1, 2, 3, 4], 2), {'tide_check': [1.5, 2.5, 3.5]})
        self.assertEqual(payroll.tide_check([5], 1), {'tide_check': [5.0]})
        self.assertEqual(payroll.tide_check([1, 2, 3], 3), {'tide_check': [2.0]})
        self.assertEqual(payroll.tide_check([2, 4, 6, 8, 10], 3), {'tide_check': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            payroll.tide_check([1, 2], 0)

    def test_rosters_sail_total(self):
        self.assertEqual(rosters.sail_total([1, 2, 3, 4], 2), {'sail_total': [1.5, 2.5, 3.5]})
        self.assertEqual(rosters.sail_total([5], 1), {'sail_total': [5.0]})
        self.assertEqual(rosters.sail_total([1, 2, 3], 3), {'sail_total': [2.0]})
        self.assertEqual(rosters.sail_total([2, 4, 6, 8, 10], 3), {'sail_total': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            rosters.sail_total([1, 2], 0)

    def test_old_name_gone(self):
        self.assertFalse(hasattr(routes, 'moving_average'))
        for f in [*pathlib.Path('kiln').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('moving_average', names(f.read_text(encoding="utf-8")), f)
