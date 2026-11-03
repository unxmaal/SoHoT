import unittest

import ast
import pathlib

from kiln import payroll
from kiln import rosters
from kiln import stock


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
        self.assertEqual(stock.window_means([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(stock.window_means([5], 1), [5.0])
        self.assertEqual(stock.window_means([1, 2, 3], 3), [2.0])
        self.assertEqual(stock.window_means([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            stock.window_means([1, 2], 0)

    def test_payroll_mast_entry(self):
        self.assertEqual(payroll.mast_entry([1, 2, 3, 4], 2), {'mast_entry': [1.5, 2.5, 3.5]})
        self.assertEqual(payroll.mast_entry([5], 1), {'mast_entry': [5.0]})
        self.assertEqual(payroll.mast_entry([1, 2, 3], 3), {'mast_entry': [2.0]})
        self.assertEqual(payroll.mast_entry([2, 4, 6, 8, 10], 3), {'mast_entry': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            payroll.mast_entry([1, 2], 0)

    def test_rosters_barge_entry(self):
        self.assertEqual(rosters.barge_entry([1, 2, 3, 4], 2), {'barge_entry': [1.5, 2.5, 3.5]})
        self.assertEqual(rosters.barge_entry([5], 1), {'barge_entry': [5.0]})
        self.assertEqual(rosters.barge_entry([1, 2, 3], 3), {'barge_entry': [2.0]})
        self.assertEqual(rosters.barge_entry([2, 4, 6, 8, 10], 3), {'barge_entry': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            rosters.barge_entry([1, 2], 0)

    def test_old_name_gone(self):
        self.assertFalse(hasattr(stock, 'moving_average'))
        for f in [*pathlib.Path('kiln').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('moving_average', names(f.read_text(encoding="utf-8")), f)
