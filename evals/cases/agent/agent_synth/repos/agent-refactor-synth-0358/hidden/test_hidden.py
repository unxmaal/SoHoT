import unittest

import ast
import pathlib

from atlas import archive
from atlas import ledger
from atlas import orders
from atlas import sensors
from atlas import shipping


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
        self.assertEqual(ledger.mark_of(95), 'A')
        self.assertEqual(ledger.mark_of(90), 'A')
        self.assertEqual(ledger.mark_of(85), 'B')
        self.assertEqual(ledger.mark_of(80), 'B')
        self.assertEqual(ledger.mark_of(61), 'D')
        self.assertEqual(ledger.mark_of(59), 'F')
        self.assertEqual(ledger.mark_of(0), 'F')

    def test_shipping_ferry_summary(self):
        self.assertEqual(shipping.ferry_summary(95), {'ferry_summary': 'A'})
        self.assertEqual(shipping.ferry_summary(90), {'ferry_summary': 'A'})
        self.assertEqual(shipping.ferry_summary(85), {'ferry_summary': 'B'})
        self.assertEqual(shipping.ferry_summary(80), {'ferry_summary': 'B'})
        self.assertEqual(shipping.ferry_summary(61), {'ferry_summary': 'D'})
        self.assertEqual(shipping.ferry_summary(59), {'ferry_summary': 'F'})
        self.assertEqual(shipping.ferry_summary(0), {'ferry_summary': 'F'})

    def test_sensors_pallet_total(self):
        self.assertEqual(sensors.pallet_total(95), {'pallet_total': 'A'})
        self.assertEqual(sensors.pallet_total(90), {'pallet_total': 'A'})
        self.assertEqual(sensors.pallet_total(85), {'pallet_total': 'B'})
        self.assertEqual(sensors.pallet_total(80), {'pallet_total': 'B'})
        self.assertEqual(sensors.pallet_total(61), {'pallet_total': 'D'})
        self.assertEqual(sensors.pallet_total(59), {'pallet_total': 'F'})
        self.assertEqual(sensors.pallet_total(0), {'pallet_total': 'F'})

    def test_archive_quay_check(self):
        self.assertEqual(archive.quay_check(95), {'quay_check': 'A'})
        self.assertEqual(archive.quay_check(90), {'quay_check': 'A'})
        self.assertEqual(archive.quay_check(85), {'quay_check': 'B'})
        self.assertEqual(archive.quay_check(80), {'quay_check': 'B'})
        self.assertEqual(archive.quay_check(61), {'quay_check': 'D'})
        self.assertEqual(archive.quay_check(59), {'quay_check': 'F'})
        self.assertEqual(archive.quay_check(0), {'quay_check': 'F'})

    def test_orders_mast_summary(self):
        self.assertEqual(orders.mast_summary(95), {'mast_summary': 'A'})
        self.assertEqual(orders.mast_summary(90), {'mast_summary': 'A'})
        self.assertEqual(orders.mast_summary(85), {'mast_summary': 'B'})
        self.assertEqual(orders.mast_summary(80), {'mast_summary': 'B'})
        self.assertEqual(orders.mast_summary(61), {'mast_summary': 'D'})
        self.assertEqual(orders.mast_summary(59), {'mast_summary': 'F'})
        self.assertEqual(orders.mast_summary(0), {'mast_summary': 'F'})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(ledger, 'grade'))
        for f in [*pathlib.Path('atlas').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('grade', names(f.read_text(encoding="utf-8")), f)
