import unittest

import ast
import pathlib

from tally import catalog
from tally import fleet
from tally import tickets


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
        self.assertEqual(tickets.count_words('a b'), 2)
        self.assertEqual(tickets.count_words('  tea  and   milk '), 3)
        self.assertEqual(tickets.count_words(''), 0)
        self.assertEqual(tickets.count_words('one'), 1)

    def test_catalog_tide_view(self):
        self.assertEqual(catalog.tide_view('a b'), {'tide_view': 2})
        self.assertEqual(catalog.tide_view('  tea  and   milk '), {'tide_view': 3})
        self.assertEqual(catalog.tide_view(''), {'tide_view': 0})
        self.assertEqual(catalog.tide_view('one'), {'tide_view': 1})

    def test_fleet_dock_summary(self):
        self.assertEqual(fleet.dock_summary('a b'), {'dock_summary': 2})
        self.assertEqual(fleet.dock_summary('  tea  and   milk '), {'dock_summary': 3})
        self.assertEqual(fleet.dock_summary(''), {'dock_summary': 0})
        self.assertEqual(fleet.dock_summary('one'), {'dock_summary': 1})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(tickets, 'word_count'))
        for f in [*pathlib.Path('tally').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('word_count', names(f.read_text(encoding="utf-8")), f)
