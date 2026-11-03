import unittest

import ast
import pathlib

from harbor import archive
from harbor import budget
from harbor import helpers
from harbor import kitchen
from harbor import stock


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
        self.assertEqual(helpers.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(helpers.rle(''), [])
        self.assertEqual(helpers.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(helpers.rle('zz'), [('z', 2)])

    def test_stock_buoy_entry(self):
        self.assertEqual(stock.buoy_entry('aaab'), {'buoy_entry': [('a', 3), ('b', 1)]})
        self.assertEqual(stock.buoy_entry(''), {'buoy_entry': []})
        self.assertEqual(stock.buoy_entry('abc'), {'buoy_entry': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(stock.buoy_entry('zz'), {'buoy_entry': [('z', 2)]})

    def test_budget_keel_check(self):
        self.assertEqual(budget.keel_check('aaab'), {'keel_check': [('a', 3), ('b', 1)]})
        self.assertEqual(budget.keel_check(''), {'keel_check': []})
        self.assertEqual(budget.keel_check('abc'), {'keel_check': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(budget.keel_check('zz'), {'keel_check': [('z', 2)]})

    def test_kitchen_tide_figure(self):
        self.assertEqual(kitchen.tide_figure('aaab'), {'tide_figure': [('a', 3), ('b', 1)]})
        self.assertEqual(kitchen.tide_figure(''), {'tide_figure': []})
        self.assertEqual(kitchen.tide_figure('abc'), {'tide_figure': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(kitchen.tide_figure('zz'), {'tide_figure': [('z', 2)]})

    def test_moved(self):
        new = pathlib.Path('harbor/helpers.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'rle' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('harbor/archive.py').read_text(encoding="utf-8")
        self.assertNotIn('rle', names(text))
