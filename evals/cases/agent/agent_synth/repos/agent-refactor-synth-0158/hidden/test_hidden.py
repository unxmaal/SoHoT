import unittest

import ast
import pathlib

from atlas import catalog
from atlas import pricing
from atlas import shipping
from atlas import stock
from atlas import tickets


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
        self.assertEqual(tickets.leap_year(2024), True)
        self.assertEqual(tickets.leap_year(1900), False)
        self.assertEqual(tickets.leap_year(2000), True)
        self.assertEqual(tickets.leap_year(2023), False)
        self.assertEqual(tickets.leap_year(2400), True)
        self.assertEqual(tickets.leap_year(2100), False)

    def test_stock_harbor_check(self):
        self.assertEqual(stock.harbor_check(2024), {'harbor_check': True})
        self.assertEqual(stock.harbor_check(1900), {'harbor_check': False})
        self.assertEqual(stock.harbor_check(2000), {'harbor_check': True})
        self.assertEqual(stock.harbor_check(2023), {'harbor_check': False})
        self.assertEqual(stock.harbor_check(2400), {'harbor_check': True})
        self.assertEqual(stock.harbor_check(2100), {'harbor_check': False})

    def test_shipping_berth_check(self):
        self.assertEqual(shipping.berth_check(2024), {'berth_check': True})
        self.assertEqual(shipping.berth_check(1900), {'berth_check': False})
        self.assertEqual(shipping.berth_check(2000), {'berth_check': True})
        self.assertEqual(shipping.berth_check(2023), {'berth_check': False})
        self.assertEqual(shipping.berth_check(2400), {'berth_check': True})
        self.assertEqual(shipping.berth_check(2100), {'berth_check': False})

    def test_pricing_dock_summary(self):
        self.assertEqual(pricing.dock_summary(2024), {'dock_summary': True})
        self.assertEqual(pricing.dock_summary(1900), {'dock_summary': False})
        self.assertEqual(pricing.dock_summary(2000), {'dock_summary': True})
        self.assertEqual(pricing.dock_summary(2023), {'dock_summary': False})
        self.assertEqual(pricing.dock_summary(2400), {'dock_summary': True})
        self.assertEqual(pricing.dock_summary(2100), {'dock_summary': False})

    def test_catalog_anchor_summary(self):
        self.assertEqual(catalog.anchor_summary(2024), {'anchor_summary': True})
        self.assertEqual(catalog.anchor_summary(1900), {'anchor_summary': False})
        self.assertEqual(catalog.anchor_summary(2000), {'anchor_summary': True})
        self.assertEqual(catalog.anchor_summary(2023), {'anchor_summary': False})
        self.assertEqual(catalog.anchor_summary(2400), {'anchor_summary': True})
        self.assertEqual(catalog.anchor_summary(2100), {'anchor_summary': False})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(tickets, 'is_leap'))
        for f in [*pathlib.Path('atlas').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('is_leap', names(f.read_text(encoding="utf-8")), f)
