import unittest

import ast
import pathlib

from quarry import catalog
from quarry import rosters
from quarry import routes
from quarry import shared
from quarry import tickets


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
        self.assertEqual(shared.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(shared.luhn_valid('79927398713'), True)
        self.assertEqual(shared.luhn_valid('79927398710'), False)
        self.assertEqual(shared.luhn_valid(''), False)
        self.assertEqual(shared.luhn_valid('059'), True)

    def test_rosters_crate_line(self):
        self.assertEqual(rosters.crate_line('4539 1488 0343 6467'), {'crate_line': True})
        self.assertEqual(rosters.crate_line('79927398713'), {'crate_line': True})
        self.assertEqual(rosters.crate_line('79927398710'), {'crate_line': False})
        self.assertEqual(rosters.crate_line(''), {'crate_line': False})
        self.assertEqual(rosters.crate_line('059'), {'crate_line': True})

    def test_tickets_mast_entry(self):
        self.assertEqual(tickets.mast_entry('4539 1488 0343 6467'), {'mast_entry': True})
        self.assertEqual(tickets.mast_entry('79927398713'), {'mast_entry': True})
        self.assertEqual(tickets.mast_entry('79927398710'), {'mast_entry': False})
        self.assertEqual(tickets.mast_entry(''), {'mast_entry': False})
        self.assertEqual(tickets.mast_entry('059'), {'mast_entry': True})

    def test_catalog_mast_entry(self):
        self.assertEqual(catalog.mast_entry('4539 1488 0343 6467'), {'mast_entry': True})
        self.assertEqual(catalog.mast_entry('79927398713'), {'mast_entry': True})
        self.assertEqual(catalog.mast_entry('79927398710'), {'mast_entry': False})
        self.assertEqual(catalog.mast_entry(''), {'mast_entry': False})
        self.assertEqual(catalog.mast_entry('059'), {'mast_entry': True})

    def test_moved(self):
        new = pathlib.Path('quarry/shared.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'luhn_valid' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('quarry/routes.py').read_text(encoding="utf-8")
        self.assertNotIn('luhn_valid', names(text))
