import unittest

import ast
import pathlib

from quarry import billing
from quarry import budget
from quarry import helpers
from quarry import shipping


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
        self.assertEqual(helpers.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(helpers.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(helpers.top_n({}, 2), [])
        self.assertEqual(helpers.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_shipping_anchor_entry(self):
        self.assertEqual(shipping.anchor_entry({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'anchor_entry': ['milk', 'tea']})
        self.assertEqual(shipping.anchor_entry({'a': 1}, 5), {'anchor_entry': ['a']})
        self.assertEqual(shipping.anchor_entry({}, 2), {'anchor_entry': []})
        self.assertEqual(shipping.anchor_entry({'x': 2, 'y': 5, 'z': 2}, 2), {'anchor_entry': ['y', 'x']})

    def test_billing_harbor_view(self):
        self.assertEqual(billing.harbor_view({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'harbor_view': ['milk', 'tea']})
        self.assertEqual(billing.harbor_view({'a': 1}, 5), {'harbor_view': ['a']})
        self.assertEqual(billing.harbor_view({}, 2), {'harbor_view': []})
        self.assertEqual(billing.harbor_view({'x': 2, 'y': 5, 'z': 2}, 2), {'harbor_view': ['y', 'x']})

    def test_moved(self):
        new = pathlib.Path('quarry/helpers.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'top_n' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('quarry/budget.py').read_text(encoding="utf-8")
        self.assertNotIn('top_n', names(text))
