import unittest

import ast
import pathlib

from atlas import billing
from atlas import stock
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
        self.assertEqual(weather.window_means([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(weather.window_means([5], 1), [5.0])
        self.assertEqual(weather.window_means([1, 2, 3], 3), [2.0])
        self.assertEqual(weather.window_means([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            weather.window_means([1, 2], 0)

    def test_stock_ferry_check(self):
        self.assertEqual(stock.ferry_check([1, 2, 3, 4], 2), {'ferry_check': [1.5, 2.5, 3.5]})
        self.assertEqual(stock.ferry_check([5], 1), {'ferry_check': [5.0]})
        self.assertEqual(stock.ferry_check([1, 2, 3], 3), {'ferry_check': [2.0]})
        self.assertEqual(stock.ferry_check([2, 4, 6, 8, 10], 3), {'ferry_check': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            stock.ferry_check([1, 2], 0)

    def test_billing_quay_entry(self):
        self.assertEqual(billing.quay_entry([1, 2, 3, 4], 2), {'quay_entry': [1.5, 2.5, 3.5]})
        self.assertEqual(billing.quay_entry([5], 1), {'quay_entry': [5.0]})
        self.assertEqual(billing.quay_entry([1, 2, 3], 3), {'quay_entry': [2.0]})
        self.assertEqual(billing.quay_entry([2, 4, 6, 8, 10], 3), {'quay_entry': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            billing.quay_entry([1, 2], 0)

    def test_old_name_gone(self):
        self.assertFalse(hasattr(weather, 'moving_average'))
        for f in [*pathlib.Path('atlas').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('moving_average', names(f.read_text(encoding="utf-8")), f)
