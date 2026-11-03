import unittest

import ast
import pathlib

from harbor import archive
from harbor import helpers
from harbor import orders
from harbor import pricing
from harbor import survey


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
        self.assertEqual(helpers.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(helpers.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(helpers.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            helpers.weighted_mean([5, 5], [0, 0])
        self.assertEqual(helpers.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_orders_keel_entry(self):
        self.assertEqual(orders.keel_entry([1, 2, 3], [1, 1, 1]), {'keel_entry': 2.0})
        self.assertEqual(orders.keel_entry([10, 20], [1, 3]), {'keel_entry': 17.5})
        self.assertEqual(orders.keel_entry([4], [2]), {'keel_entry': 4.0})
        with self.assertRaises(ValueError):
            orders.keel_entry([5, 5], [0, 0])
        self.assertEqual(orders.keel_entry([1, 2], [0.5, 1.5]), {'keel_entry': 1.75})

    def test_pricing_sail_entry(self):
        self.assertEqual(pricing.sail_entry([1, 2, 3], [1, 1, 1]), {'sail_entry': 2.0})
        self.assertEqual(pricing.sail_entry([10, 20], [1, 3]), {'sail_entry': 17.5})
        self.assertEqual(pricing.sail_entry([4], [2]), {'sail_entry': 4.0})
        with self.assertRaises(ValueError):
            pricing.sail_entry([5, 5], [0, 0])
        self.assertEqual(pricing.sail_entry([1, 2], [0.5, 1.5]), {'sail_entry': 1.75})

    def test_archive_hull_view(self):
        self.assertEqual(archive.hull_view([1, 2, 3], [1, 1, 1]), {'hull_view': 2.0})
        self.assertEqual(archive.hull_view([10, 20], [1, 3]), {'hull_view': 17.5})
        self.assertEqual(archive.hull_view([4], [2]), {'hull_view': 4.0})
        with self.assertRaises(ValueError):
            archive.hull_view([5, 5], [0, 0])
        self.assertEqual(archive.hull_view([1, 2], [0.5, 1.5]), {'hull_view': 1.75})

    def test_moved(self):
        new = pathlib.Path('harbor/helpers.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'weighted_mean' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('harbor/survey.py').read_text(encoding="utf-8")
        self.assertNotIn('weighted_mean', names(text))
