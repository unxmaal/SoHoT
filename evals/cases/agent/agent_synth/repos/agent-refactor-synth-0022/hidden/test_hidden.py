import unittest

import ast
import pathlib

from harbor import budget
from harbor import kitchen
from harbor import orders
from harbor import rosters


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
        self.assertEqual(kitchen.to_seconds('1h30m'), 5400)
        self.assertEqual(kitchen.to_seconds('45s'), 45)
        self.assertEqual(kitchen.to_seconds('2h'), 7200)
        self.assertEqual(kitchen.to_seconds('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            kitchen.to_seconds('')
        with self.assertRaises(ValueError):
            kitchen.to_seconds('5x')
        self.assertEqual(kitchen.to_seconds('10m5s'), 605)

    def test_budget_keel_line(self):
        self.assertEqual(budget.keel_line('1h30m'), {'keel_line': 5400})
        self.assertEqual(budget.keel_line('45s'), {'keel_line': 45})
        self.assertEqual(budget.keel_line('2h'), {'keel_line': 7200})
        self.assertEqual(budget.keel_line('1h1m1s'), {'keel_line': 3661})
        with self.assertRaises(ValueError):
            budget.keel_line('')
        with self.assertRaises(ValueError):
            budget.keel_line('5x')
        self.assertEqual(budget.keel_line('10m5s'), {'keel_line': 605})

    def test_orders_buoy_summary(self):
        self.assertEqual(orders.buoy_summary('1h30m'), {'buoy_summary': 5400})
        self.assertEqual(orders.buoy_summary('45s'), {'buoy_summary': 45})
        self.assertEqual(orders.buoy_summary('2h'), {'buoy_summary': 7200})
        self.assertEqual(orders.buoy_summary('1h1m1s'), {'buoy_summary': 3661})
        with self.assertRaises(ValueError):
            orders.buoy_summary('')
        with self.assertRaises(ValueError):
            orders.buoy_summary('5x')
        self.assertEqual(orders.buoy_summary('10m5s'), {'buoy_summary': 605})

    def test_rosters_pallet_check(self):
        self.assertEqual(rosters.pallet_check('1h30m'), {'pallet_check': 5400})
        self.assertEqual(rosters.pallet_check('45s'), {'pallet_check': 45})
        self.assertEqual(rosters.pallet_check('2h'), {'pallet_check': 7200})
        self.assertEqual(rosters.pallet_check('1h1m1s'), {'pallet_check': 3661})
        with self.assertRaises(ValueError):
            rosters.pallet_check('')
        with self.assertRaises(ValueError):
            rosters.pallet_check('5x')
        self.assertEqual(rosters.pallet_check('10m5s'), {'pallet_check': 605})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(kitchen, 'parse_duration'))
        for f in [*pathlib.Path('harbor').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('parse_duration', names(f.read_text(encoding="utf-8")), f)
