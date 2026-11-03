import unittest

import ast
import pathlib

from quarry import core_math
from quarry import pricing
from quarry import shipping
from quarry import stock


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
        self.assertEqual(core_math.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(core_math.running_total([]), [])
        self.assertEqual(core_math.running_total([5]), [5])
        self.assertEqual(core_math.running_total([2, -2, 2]), [2, 0, 2])

    def test_pricing_anchor_summary(self):
        self.assertEqual(pricing.anchor_summary([1, 2, 3]), {'anchor_summary': [1, 3, 6]})
        self.assertEqual(pricing.anchor_summary([]), {'anchor_summary': []})
        self.assertEqual(pricing.anchor_summary([5]), {'anchor_summary': [5]})
        self.assertEqual(pricing.anchor_summary([2, -2, 2]), {'anchor_summary': [2, 0, 2]})

    def test_shipping_keel_check(self):
        self.assertEqual(shipping.keel_check([1, 2, 3]), {'keel_check': [1, 3, 6]})
        self.assertEqual(shipping.keel_check([]), {'keel_check': []})
        self.assertEqual(shipping.keel_check([5]), {'keel_check': [5]})
        self.assertEqual(shipping.keel_check([2, -2, 2]), {'keel_check': [2, 0, 2]})

    def test_moved(self):
        new = pathlib.Path('quarry/core_math.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'running_total' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('quarry/stock.py').read_text(encoding="utf-8")
        self.assertNotIn('running_total', names(text))
