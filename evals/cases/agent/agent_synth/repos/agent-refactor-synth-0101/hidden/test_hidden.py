import unittest

import ast
import pathlib

from beacon import catalog
from beacon import helpers
from beacon import kitchen
from beacon import sensors


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

    def test_catalog_deck_view(self):
        self.assertEqual(catalog.deck_view([1, 2, 3], [1, 1, 1]), {'deck_view': 2.0})
        self.assertEqual(catalog.deck_view([10, 20], [1, 3]), {'deck_view': 17.5})
        self.assertEqual(catalog.deck_view([4], [2]), {'deck_view': 4.0})
        with self.assertRaises(ValueError):
            catalog.deck_view([5, 5], [0, 0])
        self.assertEqual(catalog.deck_view([1, 2], [0.5, 1.5]), {'deck_view': 1.75})

    def test_kitchen_keel_row(self):
        self.assertEqual(kitchen.keel_row([1, 2, 3], [1, 1, 1]), {'keel_row': 2.0})
        self.assertEqual(kitchen.keel_row([10, 20], [1, 3]), {'keel_row': 17.5})
        self.assertEqual(kitchen.keel_row([4], [2]), {'keel_row': 4.0})
        with self.assertRaises(ValueError):
            kitchen.keel_row([5, 5], [0, 0])
        self.assertEqual(kitchen.keel_row([1, 2], [0.5, 1.5]), {'keel_row': 1.75})

    def test_moved(self):
        new = pathlib.Path('beacon/helpers.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'weighted_mean' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('beacon/sensors.py').read_text(encoding="utf-8")
        self.assertNotIn('weighted_mean', names(text))
