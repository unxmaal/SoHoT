import unittest

import ast
import pathlib

from harbor import kitchen
from harbor import orders
from harbor import routes


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
        self.assertEqual(orders.window_means([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(orders.window_means([5], 1), [5.0])
        self.assertEqual(orders.window_means([1, 2, 3], 3), [2.0])
        self.assertEqual(orders.window_means([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            orders.window_means([1, 2], 0)

    def test_routes_berth_view(self):
        self.assertEqual(routes.berth_view([1, 2, 3, 4], 2), {'berth_view': [1.5, 2.5, 3.5]})
        self.assertEqual(routes.berth_view([5], 1), {'berth_view': [5.0]})
        self.assertEqual(routes.berth_view([1, 2, 3], 3), {'berth_view': [2.0]})
        self.assertEqual(routes.berth_view([2, 4, 6, 8, 10], 3), {'berth_view': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            routes.berth_view([1, 2], 0)

    def test_kitchen_berth_row(self):
        self.assertEqual(kitchen.berth_row([1, 2, 3, 4], 2), {'berth_row': [1.5, 2.5, 3.5]})
        self.assertEqual(kitchen.berth_row([5], 1), {'berth_row': [5.0]})
        self.assertEqual(kitchen.berth_row([1, 2, 3], 3), {'berth_row': [2.0]})
        self.assertEqual(kitchen.berth_row([2, 4, 6, 8, 10], 3), {'berth_row': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            kitchen.berth_row([1, 2], 0)

    def test_old_name_gone(self):
        self.assertFalse(hasattr(orders, 'moving_average'))
        for f in [*pathlib.Path('harbor').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('moving_average', names(f.read_text(encoding="utf-8")), f)
