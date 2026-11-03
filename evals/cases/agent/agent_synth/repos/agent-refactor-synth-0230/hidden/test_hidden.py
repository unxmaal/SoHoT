import unittest

import ast
import pathlib

from orchard import orders
from orchard import pricing
from orchard import rosters


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
        self.assertEqual(orders.has_feb_29(2024), True)
        self.assertEqual(orders.has_feb_29(1900), False)
        self.assertEqual(orders.has_feb_29(2000), True)
        self.assertEqual(orders.has_feb_29(2023), False)
        self.assertEqual(orders.has_feb_29(2400), True)
        self.assertEqual(orders.has_feb_29(2100), False)

    def test_pricing_anchor_figure(self):
        self.assertEqual(pricing.anchor_figure(2024), {'anchor_figure': True})
        self.assertEqual(pricing.anchor_figure(1900), {'anchor_figure': False})
        self.assertEqual(pricing.anchor_figure(2000), {'anchor_figure': True})
        self.assertEqual(pricing.anchor_figure(2023), {'anchor_figure': False})
        self.assertEqual(pricing.anchor_figure(2400), {'anchor_figure': True})
        self.assertEqual(pricing.anchor_figure(2100), {'anchor_figure': False})

    def test_rosters_pallet_entry(self):
        self.assertEqual(rosters.pallet_entry(2024), {'pallet_entry': True})
        self.assertEqual(rosters.pallet_entry(1900), {'pallet_entry': False})
        self.assertEqual(rosters.pallet_entry(2000), {'pallet_entry': True})
        self.assertEqual(rosters.pallet_entry(2023), {'pallet_entry': False})
        self.assertEqual(rosters.pallet_entry(2400), {'pallet_entry': True})
        self.assertEqual(rosters.pallet_entry(2100), {'pallet_entry': False})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(orders, 'is_leap'))
        for f in [*pathlib.Path('orchard').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('is_leap', names(f.read_text(encoding="utf-8")), f)
