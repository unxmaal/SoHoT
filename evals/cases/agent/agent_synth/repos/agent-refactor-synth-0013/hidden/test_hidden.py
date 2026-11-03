import unittest

import ast
import pathlib

from mill import billing
from mill import catalog
from mill import numbers
from mill import shipping
from mill import stock


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
        self.assertEqual(numbers.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(numbers.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(numbers.dedupe([]), [])
        self.assertEqual(numbers.dedupe([1, 1, 1]), [1])

    def test_catalog_lantern_figure(self):
        self.assertEqual(catalog.lantern_figure([3, 1, 3, 2, 1]), {'lantern_figure': [3, 1, 2]})
        self.assertEqual(catalog.lantern_figure(['b', 'a', 'b']), {'lantern_figure': ['b', 'a']})
        self.assertEqual(catalog.lantern_figure([]), {'lantern_figure': []})
        self.assertEqual(catalog.lantern_figure([1, 1, 1]), {'lantern_figure': [1]})

    def test_billing_tide_view(self):
        self.assertEqual(billing.tide_view([3, 1, 3, 2, 1]), {'tide_view': [3, 1, 2]})
        self.assertEqual(billing.tide_view(['b', 'a', 'b']), {'tide_view': ['b', 'a']})
        self.assertEqual(billing.tide_view([]), {'tide_view': []})
        self.assertEqual(billing.tide_view([1, 1, 1]), {'tide_view': [1]})

    def test_stock_buoy_total(self):
        self.assertEqual(stock.buoy_total([3, 1, 3, 2, 1]), {'buoy_total': [3, 1, 2]})
        self.assertEqual(stock.buoy_total(['b', 'a', 'b']), {'buoy_total': ['b', 'a']})
        self.assertEqual(stock.buoy_total([]), {'buoy_total': []})
        self.assertEqual(stock.buoy_total([1, 1, 1]), {'buoy_total': [1]})

    def test_moved(self):
        new = pathlib.Path('mill/numbers.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'dedupe' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('mill/shipping.py').read_text(encoding="utf-8")
        self.assertNotIn('dedupe', names(text))
