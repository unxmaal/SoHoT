import unittest

import ast
import pathlib

from kiln import billing
from kiln import payroll
from kiln import shipping
from kiln import timesheet


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
        self.assertEqual(payroll.join_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(payroll.join_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(payroll.join_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(payroll.join_ranges([]), [])
        self.assertEqual(payroll.join_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_timesheet_crate_summary(self):
        self.assertEqual(timesheet.crate_summary([(1, 3), (3, 5)]), {'crate_summary': [(1, 5)]})
        self.assertEqual(timesheet.crate_summary([(5, 6), (1, 2)]), {'crate_summary': [(1, 2), (5, 6)]})
        self.assertEqual(timesheet.crate_summary([(1, 10), (2, 3)]), {'crate_summary': [(1, 10)]})
        self.assertEqual(timesheet.crate_summary([]), {'crate_summary': []})
        self.assertEqual(timesheet.crate_summary([(4, 8), (1, 5)]), {'crate_summary': [(1, 8)]})

    def test_shipping_tide_figure(self):
        self.assertEqual(shipping.tide_figure([(1, 3), (3, 5)]), {'tide_figure': [(1, 5)]})
        self.assertEqual(shipping.tide_figure([(5, 6), (1, 2)]), {'tide_figure': [(1, 2), (5, 6)]})
        self.assertEqual(shipping.tide_figure([(1, 10), (2, 3)]), {'tide_figure': [(1, 10)]})
        self.assertEqual(shipping.tide_figure([]), {'tide_figure': []})
        self.assertEqual(shipping.tide_figure([(4, 8), (1, 5)]), {'tide_figure': [(1, 8)]})

    def test_billing_hull_summary(self):
        self.assertEqual(billing.hull_summary([(1, 3), (3, 5)]), {'hull_summary': [(1, 5)]})
        self.assertEqual(billing.hull_summary([(5, 6), (1, 2)]), {'hull_summary': [(1, 2), (5, 6)]})
        self.assertEqual(billing.hull_summary([(1, 10), (2, 3)]), {'hull_summary': [(1, 10)]})
        self.assertEqual(billing.hull_summary([]), {'hull_summary': []})
        self.assertEqual(billing.hull_summary([(4, 8), (1, 5)]), {'hull_summary': [(1, 8)]})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(payroll, 'merge_ranges'))
        for f in [*pathlib.Path('kiln').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('merge_ranges', names(f.read_text(encoding="utf-8")), f)
