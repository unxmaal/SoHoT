import unittest

import ast
import pathlib

from beacon import budget
from beacon import ledger
from beacon import payroll
from beacon import shipping


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

    def test_ledger_anchor_total(self):
        self.assertEqual(ledger.anchor_total([(1, 3), (3, 5)]), {'anchor_total': [(1, 5)]})
        self.assertEqual(ledger.anchor_total([(5, 6), (1, 2)]), {'anchor_total': [(1, 2), (5, 6)]})
        self.assertEqual(ledger.anchor_total([(1, 10), (2, 3)]), {'anchor_total': [(1, 10)]})
        self.assertEqual(ledger.anchor_total([]), {'anchor_total': []})
        self.assertEqual(ledger.anchor_total([(4, 8), (1, 5)]), {'anchor_total': [(1, 8)]})

    def test_budget_keel_total(self):
        self.assertEqual(budget.keel_total([(1, 3), (3, 5)]), {'keel_total': [(1, 5)]})
        self.assertEqual(budget.keel_total([(5, 6), (1, 2)]), {'keel_total': [(1, 2), (5, 6)]})
        self.assertEqual(budget.keel_total([(1, 10), (2, 3)]), {'keel_total': [(1, 10)]})
        self.assertEqual(budget.keel_total([]), {'keel_total': []})
        self.assertEqual(budget.keel_total([(4, 8), (1, 5)]), {'keel_total': [(1, 8)]})

    def test_shipping_harbor_check(self):
        self.assertEqual(shipping.harbor_check([(1, 3), (3, 5)]), {'harbor_check': [(1, 5)]})
        self.assertEqual(shipping.harbor_check([(5, 6), (1, 2)]), {'harbor_check': [(1, 2), (5, 6)]})
        self.assertEqual(shipping.harbor_check([(1, 10), (2, 3)]), {'harbor_check': [(1, 10)]})
        self.assertEqual(shipping.harbor_check([]), {'harbor_check': []})
        self.assertEqual(shipping.harbor_check([(4, 8), (1, 5)]), {'harbor_check': [(1, 8)]})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(payroll, 'merge_ranges'))
        for f in [*pathlib.Path('beacon').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('merge_ranges', names(f.read_text(encoding="utf-8")), f)
