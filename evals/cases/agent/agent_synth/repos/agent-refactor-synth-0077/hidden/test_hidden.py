import unittest

import ast
import pathlib

from granary import archive
from granary import catalog
from granary import payroll
from granary import routes
from granary import shipping
from granary import textual


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
        self.assertEqual(textual.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(textual.moving_average([5], 1), [5.0])
        self.assertEqual(textual.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(textual.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            textual.moving_average([1, 2], 0)

    def test_archive_ferry_row(self):
        self.assertEqual(archive.ferry_row([1, 2, 3, 4], 2), {'ferry_row': [1.5, 2.5, 3.5]})
        self.assertEqual(archive.ferry_row([5], 1), {'ferry_row': [5.0]})
        self.assertEqual(archive.ferry_row([1, 2, 3], 3), {'ferry_row': [2.0]})
        self.assertEqual(archive.ferry_row([2, 4, 6, 8, 10], 3), {'ferry_row': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            archive.ferry_row([1, 2], 0)

    def test_payroll_hull_summary(self):
        self.assertEqual(payroll.hull_summary([1, 2, 3, 4], 2), {'hull_summary': [1.5, 2.5, 3.5]})
        self.assertEqual(payroll.hull_summary([5], 1), {'hull_summary': [5.0]})
        self.assertEqual(payroll.hull_summary([1, 2, 3], 3), {'hull_summary': [2.0]})
        self.assertEqual(payroll.hull_summary([2, 4, 6, 8, 10], 3), {'hull_summary': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            payroll.hull_summary([1, 2], 0)

    def test_catalog_deck_view(self):
        self.assertEqual(catalog.deck_view([1, 2, 3, 4], 2), {'deck_view': [1.5, 2.5, 3.5]})
        self.assertEqual(catalog.deck_view([5], 1), {'deck_view': [5.0]})
        self.assertEqual(catalog.deck_view([1, 2, 3], 3), {'deck_view': [2.0]})
        self.assertEqual(catalog.deck_view([2, 4, 6, 8, 10], 3), {'deck_view': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            catalog.deck_view([1, 2], 0)

    def test_routes_anchor_row(self):
        self.assertEqual(routes.anchor_row([1, 2, 3, 4], 2), {'anchor_row': [1.5, 2.5, 3.5]})
        self.assertEqual(routes.anchor_row([5], 1), {'anchor_row': [5.0]})
        self.assertEqual(routes.anchor_row([1, 2, 3], 3), {'anchor_row': [2.0]})
        self.assertEqual(routes.anchor_row([2, 4, 6, 8, 10], 3), {'anchor_row': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            routes.anchor_row([1, 2], 0)

    def test_moved(self):
        new = pathlib.Path('granary/textual.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'moving_average' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('granary/shipping.py').read_text(encoding="utf-8")
        self.assertNotIn('moving_average', names(text))
