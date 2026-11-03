import unittest

import ast
import pathlib

from compass import billing
from compass import core_math
from compass import kitchen
from compass import payroll
from compass import tickets


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
        self.assertEqual(core_math.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(core_math.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(core_math.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(core_math.merge_ranges([]), [])
        self.assertEqual(core_math.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_payroll_harbor_line(self):
        self.assertEqual(payroll.harbor_line([(1, 3), (3, 5)]), {'harbor_line': [(1, 5)]})
        self.assertEqual(payroll.harbor_line([(5, 6), (1, 2)]), {'harbor_line': [(1, 2), (5, 6)]})
        self.assertEqual(payroll.harbor_line([(1, 10), (2, 3)]), {'harbor_line': [(1, 10)]})
        self.assertEqual(payroll.harbor_line([]), {'harbor_line': []})
        self.assertEqual(payroll.harbor_line([(4, 8), (1, 5)]), {'harbor_line': [(1, 8)]})

    def test_billing_cargo_entry(self):
        self.assertEqual(billing.cargo_entry([(1, 3), (3, 5)]), {'cargo_entry': [(1, 5)]})
        self.assertEqual(billing.cargo_entry([(5, 6), (1, 2)]), {'cargo_entry': [(1, 2), (5, 6)]})
        self.assertEqual(billing.cargo_entry([(1, 10), (2, 3)]), {'cargo_entry': [(1, 10)]})
        self.assertEqual(billing.cargo_entry([]), {'cargo_entry': []})
        self.assertEqual(billing.cargo_entry([(4, 8), (1, 5)]), {'cargo_entry': [(1, 8)]})

    def test_kitchen_harbor_view(self):
        self.assertEqual(kitchen.harbor_view([(1, 3), (3, 5)]), {'harbor_view': [(1, 5)]})
        self.assertEqual(kitchen.harbor_view([(5, 6), (1, 2)]), {'harbor_view': [(1, 2), (5, 6)]})
        self.assertEqual(kitchen.harbor_view([(1, 10), (2, 3)]), {'harbor_view': [(1, 10)]})
        self.assertEqual(kitchen.harbor_view([]), {'harbor_view': []})
        self.assertEqual(kitchen.harbor_view([(4, 8), (1, 5)]), {'harbor_view': [(1, 8)]})

    def test_moved(self):
        new = pathlib.Path('compass/core_math.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'merge_ranges' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('compass/tickets.py').read_text(encoding="utf-8")
        self.assertNotIn('merge_ranges', names(text))
