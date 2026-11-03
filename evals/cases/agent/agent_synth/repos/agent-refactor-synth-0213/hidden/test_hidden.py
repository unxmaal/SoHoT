import unittest

import ast
import pathlib

from harbor import common
from harbor import fleet
from harbor import routes
from harbor import shipping


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
        self.assertEqual(common.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(common.luhn_valid('79927398713'), True)
        self.assertEqual(common.luhn_valid('79927398710'), False)
        self.assertEqual(common.luhn_valid(''), False)
        self.assertEqual(common.luhn_valid('059'), True)

    def test_fleet_quay_figure(self):
        self.assertEqual(fleet.quay_figure('4539 1488 0343 6467'), {'quay_figure': True})
        self.assertEqual(fleet.quay_figure('79927398713'), {'quay_figure': True})
        self.assertEqual(fleet.quay_figure('79927398710'), {'quay_figure': False})
        self.assertEqual(fleet.quay_figure(''), {'quay_figure': False})
        self.assertEqual(fleet.quay_figure('059'), {'quay_figure': True})

    def test_routes_mast_check(self):
        self.assertEqual(routes.mast_check('4539 1488 0343 6467'), {'mast_check': True})
        self.assertEqual(routes.mast_check('79927398713'), {'mast_check': True})
        self.assertEqual(routes.mast_check('79927398710'), {'mast_check': False})
        self.assertEqual(routes.mast_check(''), {'mast_check': False})
        self.assertEqual(routes.mast_check('059'), {'mast_check': True})

    def test_moved(self):
        new = pathlib.Path('harbor/common.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'luhn_valid' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('harbor/shipping.py').read_text(encoding="utf-8")
        self.assertNotIn('luhn_valid', names(text))
