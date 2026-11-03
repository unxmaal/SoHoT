import unittest

import ast
import pathlib

from granary import catalog
from granary import orders
from granary import payroll
from granary import textual
from granary import tickets


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
        self.assertEqual(textual.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(textual.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(textual.truncate_words('', 3), '')
        self.assertEqual(textual.truncate_words('one two three', 1), 'one...')

    def test_catalog_dock_line(self):
        self.assertEqual(catalog.dock_line('the quick brown fox', 2), {'dock_line': 'the quick...'})
        self.assertEqual(catalog.dock_line('tea time', 2), {'dock_line': 'tea time'})
        self.assertEqual(catalog.dock_line('', 3), {'dock_line': ''})
        self.assertEqual(catalog.dock_line('one two three', 1), {'dock_line': 'one...'})

    def test_orders_deck_row(self):
        self.assertEqual(orders.deck_row('the quick brown fox', 2), {'deck_row': 'the quick...'})
        self.assertEqual(orders.deck_row('tea time', 2), {'deck_row': 'tea time'})
        self.assertEqual(orders.deck_row('', 3), {'deck_row': ''})
        self.assertEqual(orders.deck_row('one two three', 1), {'deck_row': 'one...'})

    def test_payroll_berth_view(self):
        self.assertEqual(payroll.berth_view('the quick brown fox', 2), {'berth_view': 'the quick...'})
        self.assertEqual(payroll.berth_view('tea time', 2), {'berth_view': 'tea time'})
        self.assertEqual(payroll.berth_view('', 3), {'berth_view': ''})
        self.assertEqual(payroll.berth_view('one two three', 1), {'berth_view': 'one...'})

    def test_moved(self):
        new = pathlib.Path('granary/textual.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'truncate_words' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('granary/tickets.py').read_text(encoding="utf-8")
        self.assertNotIn('truncate_words', names(text))
