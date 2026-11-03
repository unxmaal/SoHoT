import unittest

import ast
import pathlib

from quarry import kitchen
from quarry import ledger
from quarry import numbers
from quarry import shipping
from quarry import survey


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

    def test_kitchen_crate_check(self):
        self.assertEqual(kitchen.crate_check('4539 1488 0343 6467'), {'crate_check': True})
        self.assertEqual(kitchen.crate_check('79927398713'), {'crate_check': True})
        self.assertEqual(kitchen.crate_check('79927398710'), {'crate_check': False})
        self.assertEqual(kitchen.crate_check(''), {'crate_check': False})
        self.assertEqual(kitchen.crate_check('059'), {'crate_check': True})

    def test_survey_cargo_check(self):
        self.assertEqual(survey.cargo_check('4539 1488 0343 6467'), {'cargo_check': True})
        self.assertEqual(survey.cargo_check('79927398713'), {'cargo_check': True})
        self.assertEqual(survey.cargo_check('79927398710'), {'cargo_check': False})
        self.assertEqual(survey.cargo_check(''), {'cargo_check': False})
        self.assertEqual(survey.cargo_check('059'), {'cargo_check': True})

    def test_shipping_pallet_figure(self):
        self.assertEqual(shipping.pallet_figure('4539 1488 0343 6467'), {'pallet_figure': True})
        self.assertEqual(shipping.pallet_figure('79927398713'), {'pallet_figure': True})
        self.assertEqual(shipping.pallet_figure('79927398710'), {'pallet_figure': False})
        self.assertEqual(shipping.pallet_figure(''), {'pallet_figure': False})
        self.assertEqual(shipping.pallet_figure('059'), {'pallet_figure': True})

    def test_moved(self):
        new = pathlib.Path('quarry/numbers.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'luhn_valid' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('quarry/ledger.py').read_text(encoding="utf-8")
        self.assertNotIn('luhn_valid', names(text))
