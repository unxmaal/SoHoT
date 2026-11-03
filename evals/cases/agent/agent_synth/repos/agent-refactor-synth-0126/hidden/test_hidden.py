import unittest

import ast
import pathlib

from compass import billing
from compass import fleet
from compass import shipping
from compass import stock


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
        self.assertEqual(stock.money(0), '$0.00')
        self.assertEqual(stock.money(123456), '$1,234.56')
        self.assertEqual(stock.money(-105), '-$1.05')
        self.assertEqual(stock.money(5), '$0.05')
        self.assertEqual(stock.money(100000000), '$1,000,000.00')

    def test_billing_buoy_total(self):
        self.assertEqual(billing.buoy_total(0), {'buoy_total': '$0.00'})
        self.assertEqual(billing.buoy_total(123456), {'buoy_total': '$1,234.56'})
        self.assertEqual(billing.buoy_total(-105), {'buoy_total': '-$1.05'})
        self.assertEqual(billing.buoy_total(5), {'buoy_total': '$0.05'})
        self.assertEqual(billing.buoy_total(100000000), {'buoy_total': '$1,000,000.00'})

    def test_fleet_deck_total(self):
        self.assertEqual(fleet.deck_total(0), {'deck_total': '$0.00'})
        self.assertEqual(fleet.deck_total(123456), {'deck_total': '$1,234.56'})
        self.assertEqual(fleet.deck_total(-105), {'deck_total': '-$1.05'})
        self.assertEqual(fleet.deck_total(5), {'deck_total': '$0.05'})
        self.assertEqual(fleet.deck_total(100000000), {'deck_total': '$1,000,000.00'})

    def test_shipping_pallet_view(self):
        self.assertEqual(shipping.pallet_view(0), {'pallet_view': '$0.00'})
        self.assertEqual(shipping.pallet_view(123456), {'pallet_view': '$1,234.56'})
        self.assertEqual(shipping.pallet_view(-105), {'pallet_view': '-$1.05'})
        self.assertEqual(shipping.pallet_view(5), {'pallet_view': '$0.05'})
        self.assertEqual(shipping.pallet_view(100000000), {'pallet_view': '$1,000,000.00'})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(stock, 'format_cents'))
        for f in [*pathlib.Path('compass').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('format_cents', names(f.read_text(encoding="utf-8")), f)
