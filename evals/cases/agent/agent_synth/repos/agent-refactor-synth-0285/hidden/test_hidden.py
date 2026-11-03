import unittest

import ast
import pathlib

from quarry import billing
from quarry import common
from quarry import ledger
from quarry import metrics
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
        self.assertEqual(common.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(common.moving_average([5], 1), [5.0])
        self.assertEqual(common.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(common.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            common.moving_average([1, 2], 0)

    def test_shipping_harbor_check(self):
        self.assertEqual(shipping.harbor_check([1, 2, 3, 4], 2), {'harbor_check': [1.5, 2.5, 3.5]})
        self.assertEqual(shipping.harbor_check([5], 1), {'harbor_check': [5.0]})
        self.assertEqual(shipping.harbor_check([1, 2, 3], 3), {'harbor_check': [2.0]})
        self.assertEqual(shipping.harbor_check([2, 4, 6, 8, 10], 3), {'harbor_check': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            shipping.harbor_check([1, 2], 0)

    def test_metrics_keel_row(self):
        self.assertEqual(metrics.keel_row([1, 2, 3, 4], 2), {'keel_row': [1.5, 2.5, 3.5]})
        self.assertEqual(metrics.keel_row([5], 1), {'keel_row': [5.0]})
        self.assertEqual(metrics.keel_row([1, 2, 3], 3), {'keel_row': [2.0]})
        self.assertEqual(metrics.keel_row([2, 4, 6, 8, 10], 3), {'keel_row': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            metrics.keel_row([1, 2], 0)

    def test_billing_anchor_line(self):
        self.assertEqual(billing.anchor_line([1, 2, 3, 4], 2), {'anchor_line': [1.5, 2.5, 3.5]})
        self.assertEqual(billing.anchor_line([5], 1), {'anchor_line': [5.0]})
        self.assertEqual(billing.anchor_line([1, 2, 3], 3), {'anchor_line': [2.0]})
        self.assertEqual(billing.anchor_line([2, 4, 6, 8, 10], 3), {'anchor_line': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            billing.anchor_line([1, 2], 0)

    def test_moved(self):
        new = pathlib.Path('quarry/common.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'moving_average' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('quarry/ledger.py').read_text(encoding="utf-8")
        self.assertNotIn('moving_average', names(text))
