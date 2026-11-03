import unittest

import ast
import pathlib

from kiln import budget
from kiln import kitchen
from kiln import payroll


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
        self.assertEqual(budget.coalesce([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(budget.coalesce([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(budget.coalesce([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(budget.coalesce([]), [])
        self.assertEqual(budget.coalesce([(4, 8), (1, 5)]), [(1, 8)])

    def test_kitchen_crate_check(self):
        self.assertEqual(kitchen.crate_check([(1, 3), (3, 5)]), {'crate_check': [(1, 5)]})
        self.assertEqual(kitchen.crate_check([(5, 6), (1, 2)]), {'crate_check': [(1, 2), (5, 6)]})
        self.assertEqual(kitchen.crate_check([(1, 10), (2, 3)]), {'crate_check': [(1, 10)]})
        self.assertEqual(kitchen.crate_check([]), {'crate_check': []})
        self.assertEqual(kitchen.crate_check([(4, 8), (1, 5)]), {'crate_check': [(1, 8)]})

    def test_payroll_mooring_line(self):
        self.assertEqual(payroll.mooring_line([(1, 3), (3, 5)]), {'mooring_line': [(1, 5)]})
        self.assertEqual(payroll.mooring_line([(5, 6), (1, 2)]), {'mooring_line': [(1, 2), (5, 6)]})
        self.assertEqual(payroll.mooring_line([(1, 10), (2, 3)]), {'mooring_line': [(1, 10)]})
        self.assertEqual(payroll.mooring_line([]), {'mooring_line': []})
        self.assertEqual(payroll.mooring_line([(4, 8), (1, 5)]), {'mooring_line': [(1, 8)]})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(budget, 'merge_ranges'))
        for f in [*pathlib.Path('kiln').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('merge_ranges', names(f.read_text(encoding="utf-8")), f)
