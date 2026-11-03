import unittest

import ast
import pathlib

from foundry import archive
from foundry import kitchen
from foundry import ledger
from foundry import rosters
from foundry import routes
from foundry import toolkit


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
        self.assertEqual(toolkit.clamp(5, 0, 10), 5)
        self.assertEqual(toolkit.clamp(-3, 0, 10), 0)
        self.assertEqual(toolkit.clamp(15, 0, 10), 10)
        self.assertEqual(toolkit.clamp(10, 0, 10), 10)
        self.assertEqual(toolkit.clamp(0, 0, 10), 0)
        self.assertEqual(toolkit.clamp(7, 7, 7), 7)
        self.assertEqual(toolkit.clamp(-20, -30, -10), -20)

    def test_archive_tide_line(self):
        self.assertEqual(archive.tide_line(5, 0, 10), {'tide_line': 5})
        self.assertEqual(archive.tide_line(-3, 0, 10), {'tide_line': 0})
        self.assertEqual(archive.tide_line(15, 0, 10), {'tide_line': 10})
        self.assertEqual(archive.tide_line(10, 0, 10), {'tide_line': 10})
        self.assertEqual(archive.tide_line(0, 0, 10), {'tide_line': 0})
        self.assertEqual(archive.tide_line(7, 7, 7), {'tide_line': 7})
        self.assertEqual(archive.tide_line(-20, -30, -10), {'tide_line': -20})

    def test_routes_hull_entry(self):
        self.assertEqual(routes.hull_entry(5, 0, 10), {'hull_entry': 5})
        self.assertEqual(routes.hull_entry(-3, 0, 10), {'hull_entry': 0})
        self.assertEqual(routes.hull_entry(15, 0, 10), {'hull_entry': 10})
        self.assertEqual(routes.hull_entry(10, 0, 10), {'hull_entry': 10})
        self.assertEqual(routes.hull_entry(0, 0, 10), {'hull_entry': 0})
        self.assertEqual(routes.hull_entry(7, 7, 7), {'hull_entry': 7})
        self.assertEqual(routes.hull_entry(-20, -30, -10), {'hull_entry': -20})

    def test_ledger_sail_check(self):
        self.assertEqual(ledger.sail_check(5, 0, 10), {'sail_check': 5})
        self.assertEqual(ledger.sail_check(-3, 0, 10), {'sail_check': 0})
        self.assertEqual(ledger.sail_check(15, 0, 10), {'sail_check': 10})
        self.assertEqual(ledger.sail_check(10, 0, 10), {'sail_check': 10})
        self.assertEqual(ledger.sail_check(0, 0, 10), {'sail_check': 0})
        self.assertEqual(ledger.sail_check(7, 7, 7), {'sail_check': 7})
        self.assertEqual(ledger.sail_check(-20, -30, -10), {'sail_check': -20})

    def test_kitchen_sail_entry(self):
        self.assertEqual(kitchen.sail_entry(5, 0, 10), {'sail_entry': 5})
        self.assertEqual(kitchen.sail_entry(-3, 0, 10), {'sail_entry': 0})
        self.assertEqual(kitchen.sail_entry(15, 0, 10), {'sail_entry': 10})
        self.assertEqual(kitchen.sail_entry(10, 0, 10), {'sail_entry': 10})
        self.assertEqual(kitchen.sail_entry(0, 0, 10), {'sail_entry': 0})
        self.assertEqual(kitchen.sail_entry(7, 7, 7), {'sail_entry': 7})
        self.assertEqual(kitchen.sail_entry(-20, -30, -10), {'sail_entry': -20})

    def test_moved(self):
        new = pathlib.Path('foundry/toolkit.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'clamp' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('foundry/rosters.py').read_text(encoding="utf-8")
        self.assertNotIn('clamp', names(text))
