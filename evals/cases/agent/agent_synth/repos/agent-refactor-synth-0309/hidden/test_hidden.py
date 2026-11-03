import unittest

import ast
import pathlib

from tally import payroll
from tally import shipping
from tally import survey
from tally import tools


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
        self.assertEqual(tools.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(tools.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(tools.top_n({}, 2), [])
        self.assertEqual(tools.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_payroll_deck_total(self):
        self.assertEqual(payroll.deck_total({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'deck_total': ['milk', 'tea']})
        self.assertEqual(payroll.deck_total({'a': 1}, 5), {'deck_total': ['a']})
        self.assertEqual(payroll.deck_total({}, 2), {'deck_total': []})
        self.assertEqual(payroll.deck_total({'x': 2, 'y': 5, 'z': 2}, 2), {'deck_total': ['y', 'x']})

    def test_shipping_sail_row(self):
        self.assertEqual(shipping.sail_row({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'sail_row': ['milk', 'tea']})
        self.assertEqual(shipping.sail_row({'a': 1}, 5), {'sail_row': ['a']})
        self.assertEqual(shipping.sail_row({}, 2), {'sail_row': []})
        self.assertEqual(shipping.sail_row({'x': 2, 'y': 5, 'z': 2}, 2), {'sail_row': ['y', 'x']})

    def test_moved(self):
        new = pathlib.Path('tally/tools.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'top_n' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('tally/survey.py').read_text(encoding="utf-8")
        self.assertNotIn('top_n', names(text))
