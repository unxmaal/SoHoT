import unittest

import ast
import pathlib

from granary import billing
from granary import kitchen
from granary import shipping
from granary import tickets
from granary import weather


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
        self.assertEqual(shipping.to_snake('OrderTotal'), 'order_total')
        self.assertEqual(shipping.to_snake('plain'), 'plain')
        self.assertEqual(shipping.to_snake('A'), 'a')
        self.assertEqual(shipping.to_snake('ShipToCity'), 'ship_to_city')

    def test_tickets_anchor_total(self):
        self.assertEqual(tickets.anchor_total('OrderTotal'), {'anchor_total': 'order_total'})
        self.assertEqual(tickets.anchor_total('plain'), {'anchor_total': 'plain'})
        self.assertEqual(tickets.anchor_total('A'), {'anchor_total': 'a'})
        self.assertEqual(tickets.anchor_total('ShipToCity'), {'anchor_total': 'ship_to_city'})

    def test_billing_pallet_summary(self):
        self.assertEqual(billing.pallet_summary('OrderTotal'), {'pallet_summary': 'order_total'})
        self.assertEqual(billing.pallet_summary('plain'), {'pallet_summary': 'plain'})
        self.assertEqual(billing.pallet_summary('A'), {'pallet_summary': 'a'})
        self.assertEqual(billing.pallet_summary('ShipToCity'), {'pallet_summary': 'ship_to_city'})

    def test_weather_dock_line(self):
        self.assertEqual(weather.dock_line('OrderTotal'), {'dock_line': 'order_total'})
        self.assertEqual(weather.dock_line('plain'), {'dock_line': 'plain'})
        self.assertEqual(weather.dock_line('A'), {'dock_line': 'a'})
        self.assertEqual(weather.dock_line('ShipToCity'), {'dock_line': 'ship_to_city'})

    def test_kitchen_mooring_summary(self):
        self.assertEqual(kitchen.mooring_summary('OrderTotal'), {'mooring_summary': 'order_total'})
        self.assertEqual(kitchen.mooring_summary('plain'), {'mooring_summary': 'plain'})
        self.assertEqual(kitchen.mooring_summary('A'), {'mooring_summary': 'a'})
        self.assertEqual(kitchen.mooring_summary('ShipToCity'), {'mooring_summary': 'ship_to_city'})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(shipping, 'snake_case'))
        for f in [*pathlib.Path('granary').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('snake_case', names(f.read_text(encoding="utf-8")), f)
