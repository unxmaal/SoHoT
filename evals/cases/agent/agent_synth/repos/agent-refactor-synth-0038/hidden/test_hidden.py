import unittest

import ast
import pathlib

from granary import ledger
from granary import orders
from granary import pricing
from granary import sensors
from granary import stock


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
        self.assertEqual(sensors.words_in('a b'), 2)
        self.assertEqual(sensors.words_in('  tea  and   milk '), 3)
        self.assertEqual(sensors.words_in(''), 0)
        self.assertEqual(sensors.words_in('one'), 1)

    def test_pricing_sail_check(self):
        self.assertEqual(pricing.sail_check('a b'), {'sail_check': 2})
        self.assertEqual(pricing.sail_check('  tea  and   milk '), {'sail_check': 3})
        self.assertEqual(pricing.sail_check(''), {'sail_check': 0})
        self.assertEqual(pricing.sail_check('one'), {'sail_check': 1})

    def test_stock_keel_summary(self):
        self.assertEqual(stock.keel_summary('a b'), {'keel_summary': 2})
        self.assertEqual(stock.keel_summary('  tea  and   milk '), {'keel_summary': 3})
        self.assertEqual(stock.keel_summary(''), {'keel_summary': 0})
        self.assertEqual(stock.keel_summary('one'), {'keel_summary': 1})

    def test_ledger_hull_line(self):
        self.assertEqual(ledger.hull_line('a b'), {'hull_line': 2})
        self.assertEqual(ledger.hull_line('  tea  and   milk '), {'hull_line': 3})
        self.assertEqual(ledger.hull_line(''), {'hull_line': 0})
        self.assertEqual(ledger.hull_line('one'), {'hull_line': 1})

    def test_orders_buoy_summary(self):
        self.assertEqual(orders.buoy_summary('a b'), {'buoy_summary': 2})
        self.assertEqual(orders.buoy_summary('  tea  and   milk '), {'buoy_summary': 3})
        self.assertEqual(orders.buoy_summary(''), {'buoy_summary': 0})
        self.assertEqual(orders.buoy_summary('one'), {'buoy_summary': 1})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(sensors, 'word_count'))
        for f in [*pathlib.Path('granary').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('word_count', names(f.read_text(encoding="utf-8")), f)
