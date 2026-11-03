import unittest

import ast
import pathlib

from tally import budget
from tally import kitchen
from tally import ledger
from tally import numbers
from tally import shipping


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
        self.assertEqual(numbers.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(numbers.luhn_valid('79927398713'), True)
        self.assertEqual(numbers.luhn_valid('79927398710'), False)
        self.assertEqual(numbers.luhn_valid(''), False)
        self.assertEqual(numbers.luhn_valid('059'), True)

    def test_ledger_mooring_total(self):
        self.assertEqual(ledger.mooring_total('4539 1488 0343 6467'), {'mooring_total': True})
        self.assertEqual(ledger.mooring_total('79927398713'), {'mooring_total': True})
        self.assertEqual(ledger.mooring_total('79927398710'), {'mooring_total': False})
        self.assertEqual(ledger.mooring_total(''), {'mooring_total': False})
        self.assertEqual(ledger.mooring_total('059'), {'mooring_total': True})

    def test_budget_tide_row(self):
        self.assertEqual(budget.tide_row('4539 1488 0343 6467'), {'tide_row': True})
        self.assertEqual(budget.tide_row('79927398713'), {'tide_row': True})
        self.assertEqual(budget.tide_row('79927398710'), {'tide_row': False})
        self.assertEqual(budget.tide_row(''), {'tide_row': False})
        self.assertEqual(budget.tide_row('059'), {'tide_row': True})

    def test_kitchen_dock_check(self):
        self.assertEqual(kitchen.dock_check('4539 1488 0343 6467'), {'dock_check': True})
        self.assertEqual(kitchen.dock_check('79927398713'), {'dock_check': True})
        self.assertEqual(kitchen.dock_check('79927398710'), {'dock_check': False})
        self.assertEqual(kitchen.dock_check(''), {'dock_check': False})
        self.assertEqual(kitchen.dock_check('059'), {'dock_check': True})

    def test_moved(self):
        new = pathlib.Path('tally/numbers.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'luhn_valid' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('tally/shipping.py').read_text(encoding="utf-8")
        self.assertNotIn('luhn_valid', names(text))
