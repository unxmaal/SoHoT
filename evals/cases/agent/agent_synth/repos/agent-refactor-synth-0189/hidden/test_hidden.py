import unittest

import ast
import pathlib

from tally import catalog
from tally import common
from tally import fleet
from tally import payroll
from tally import pricing
from tally import routes


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

    def test_pricing_quay_summary(self):
        self.assertEqual(pricing.quay_summary([1, 2, 3, 4], 2), {'quay_summary': [1.5, 2.5, 3.5]})
        self.assertEqual(pricing.quay_summary([5], 1), {'quay_summary': [5.0]})
        self.assertEqual(pricing.quay_summary([1, 2, 3], 3), {'quay_summary': [2.0]})
        self.assertEqual(pricing.quay_summary([2, 4, 6, 8, 10], 3), {'quay_summary': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            pricing.quay_summary([1, 2], 0)

    def test_routes_pallet_summary(self):
        self.assertEqual(routes.pallet_summary([1, 2, 3, 4], 2), {'pallet_summary': [1.5, 2.5, 3.5]})
        self.assertEqual(routes.pallet_summary([5], 1), {'pallet_summary': [5.0]})
        self.assertEqual(routes.pallet_summary([1, 2, 3], 3), {'pallet_summary': [2.0]})
        self.assertEqual(routes.pallet_summary([2, 4, 6, 8, 10], 3), {'pallet_summary': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            routes.pallet_summary([1, 2], 0)

    def test_catalog_deck_check(self):
        self.assertEqual(catalog.deck_check([1, 2, 3, 4], 2), {'deck_check': [1.5, 2.5, 3.5]})
        self.assertEqual(catalog.deck_check([5], 1), {'deck_check': [5.0]})
        self.assertEqual(catalog.deck_check([1, 2, 3], 3), {'deck_check': [2.0]})
        self.assertEqual(catalog.deck_check([2, 4, 6, 8, 10], 3), {'deck_check': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            catalog.deck_check([1, 2], 0)

    def test_fleet_barge_total(self):
        self.assertEqual(fleet.barge_total([1, 2, 3, 4], 2), {'barge_total': [1.5, 2.5, 3.5]})
        self.assertEqual(fleet.barge_total([5], 1), {'barge_total': [5.0]})
        self.assertEqual(fleet.barge_total([1, 2, 3], 3), {'barge_total': [2.0]})
        self.assertEqual(fleet.barge_total([2, 4, 6, 8, 10], 3), {'barge_total': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            fleet.barge_total([1, 2], 0)

    def test_moved(self):
        new = pathlib.Path('tally/common.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'moving_average' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('tally/payroll.py').read_text(encoding="utf-8")
        self.assertNotIn('moving_average', names(text))
