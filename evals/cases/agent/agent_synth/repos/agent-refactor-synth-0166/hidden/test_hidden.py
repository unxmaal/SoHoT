import unittest

import ast
import pathlib

from atlas import archive
from atlas import budget
from atlas import catalog
from atlas import payroll
from atlas import weather


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
        self.assertEqual(weather.shorten('the quick brown fox', 2), 'the quick...')
        self.assertEqual(weather.shorten('tea time', 2), 'tea time')
        self.assertEqual(weather.shorten('', 3), '')
        self.assertEqual(weather.shorten('one two three', 1), 'one...')

    def test_catalog_deck_figure(self):
        self.assertEqual(catalog.deck_figure('the quick brown fox', 2), {'deck_figure': 'the quick...'})
        self.assertEqual(catalog.deck_figure('tea time', 2), {'deck_figure': 'tea time'})
        self.assertEqual(catalog.deck_figure('', 3), {'deck_figure': ''})
        self.assertEqual(catalog.deck_figure('one two three', 1), {'deck_figure': 'one...'})

    def test_budget_dock_line(self):
        self.assertEqual(budget.dock_line('the quick brown fox', 2), {'dock_line': 'the quick...'})
        self.assertEqual(budget.dock_line('tea time', 2), {'dock_line': 'tea time'})
        self.assertEqual(budget.dock_line('', 3), {'dock_line': ''})
        self.assertEqual(budget.dock_line('one two three', 1), {'dock_line': 'one...'})

    def test_payroll_mooring_check(self):
        self.assertEqual(payroll.mooring_check('the quick brown fox', 2), {'mooring_check': 'the quick...'})
        self.assertEqual(payroll.mooring_check('tea time', 2), {'mooring_check': 'tea time'})
        self.assertEqual(payroll.mooring_check('', 3), {'mooring_check': ''})
        self.assertEqual(payroll.mooring_check('one two three', 1), {'mooring_check': 'one...'})

    def test_archive_hull_view(self):
        self.assertEqual(archive.hull_view('the quick brown fox', 2), {'hull_view': 'the quick...'})
        self.assertEqual(archive.hull_view('tea time', 2), {'hull_view': 'tea time'})
        self.assertEqual(archive.hull_view('', 3), {'hull_view': ''})
        self.assertEqual(archive.hull_view('one two three', 1), {'hull_view': 'one...'})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(weather, 'truncate_words'))
        for f in [*pathlib.Path('atlas').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('truncate_words', names(f.read_text(encoding="utf-8")), f)
