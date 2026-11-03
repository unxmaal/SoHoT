import unittest

import ast
import pathlib

from atlas import archive
from atlas import billing
from atlas import budget
from atlas import shipping
from atlas import toolkit
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
        self.assertEqual(toolkit.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(toolkit.invert({}), {})
        self.assertEqual(toolkit.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(toolkit.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_billing_ferry_line(self):
        self.assertEqual(billing.ferry_line({'a': 1, 'b': 2, 'c': 1}), {'ferry_line': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(billing.ferry_line({}), {'ferry_line': {}})
        self.assertEqual(billing.ferry_line({'x': 'y'}), {'ferry_line': {'y': ['x']}})
        self.assertEqual(billing.ferry_line({'q': 0, 'p': 0, 'r': 0}), {'ferry_line': {0: ['p', 'q', 'r']}})

    def test_weather_crate_total(self):
        self.assertEqual(weather.crate_total({'a': 1, 'b': 2, 'c': 1}), {'crate_total': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(weather.crate_total({}), {'crate_total': {}})
        self.assertEqual(weather.crate_total({'x': 'y'}), {'crate_total': {'y': ['x']}})
        self.assertEqual(weather.crate_total({'q': 0, 'p': 0, 'r': 0}), {'crate_total': {0: ['p', 'q', 'r']}})

    def test_budget_sail_view(self):
        self.assertEqual(budget.sail_view({'a': 1, 'b': 2, 'c': 1}), {'sail_view': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(budget.sail_view({}), {'sail_view': {}})
        self.assertEqual(budget.sail_view({'x': 'y'}), {'sail_view': {'y': ['x']}})
        self.assertEqual(budget.sail_view({'q': 0, 'p': 0, 'r': 0}), {'sail_view': {0: ['p', 'q', 'r']}})

    def test_archive_barge_line(self):
        self.assertEqual(archive.barge_line({'a': 1, 'b': 2, 'c': 1}), {'barge_line': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(archive.barge_line({}), {'barge_line': {}})
        self.assertEqual(archive.barge_line({'x': 'y'}), {'barge_line': {'y': ['x']}})
        self.assertEqual(archive.barge_line({'q': 0, 'p': 0, 'r': 0}), {'barge_line': {0: ['p', 'q', 'r']}})

    def test_moved(self):
        new = pathlib.Path('atlas/toolkit.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'invert' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('atlas/shipping.py').read_text(encoding="utf-8")
        self.assertNotIn('invert', names(text))
