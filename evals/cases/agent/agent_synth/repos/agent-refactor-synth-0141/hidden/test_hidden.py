import unittest

import ast
import pathlib

from wharf import fleet
from wharf import ledger
from wharf import stock
from wharf import textual


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
        self.assertEqual(textual.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(textual.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(textual.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(textual.merge_ranges([]), [])
        self.assertEqual(textual.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_fleet_keel_summary(self):
        self.assertEqual(fleet.keel_summary([(1, 3), (3, 5)]), {'keel_summary': [(1, 5)]})
        self.assertEqual(fleet.keel_summary([(5, 6), (1, 2)]), {'keel_summary': [(1, 2), (5, 6)]})
        self.assertEqual(fleet.keel_summary([(1, 10), (2, 3)]), {'keel_summary': [(1, 10)]})
        self.assertEqual(fleet.keel_summary([]), {'keel_summary': []})
        self.assertEqual(fleet.keel_summary([(4, 8), (1, 5)]), {'keel_summary': [(1, 8)]})

    def test_ledger_crate_view(self):
        self.assertEqual(ledger.crate_view([(1, 3), (3, 5)]), {'crate_view': [(1, 5)]})
        self.assertEqual(ledger.crate_view([(5, 6), (1, 2)]), {'crate_view': [(1, 2), (5, 6)]})
        self.assertEqual(ledger.crate_view([(1, 10), (2, 3)]), {'crate_view': [(1, 10)]})
        self.assertEqual(ledger.crate_view([]), {'crate_view': []})
        self.assertEqual(ledger.crate_view([(4, 8), (1, 5)]), {'crate_view': [(1, 8)]})

    def test_moved(self):
        new = pathlib.Path('wharf/textual.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'merge_ranges' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('wharf/stock.py').read_text(encoding="utf-8")
        self.assertNotIn('merge_ranges', names(text))
