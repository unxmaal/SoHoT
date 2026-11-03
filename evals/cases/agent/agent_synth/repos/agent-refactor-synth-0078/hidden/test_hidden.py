import unittest

import ast
import pathlib

from lantern import catalog
from lantern import payroll
from lantern import routes


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
        self.assertEqual(routes.window_means([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(routes.window_means([5], 1), [5.0])
        self.assertEqual(routes.window_means([1, 2, 3], 3), [2.0])
        self.assertEqual(routes.window_means([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            routes.window_means([1, 2], 0)

    def test_catalog_harbor_check(self):
        self.assertEqual(catalog.harbor_check([1, 2, 3, 4], 2), {'harbor_check': [1.5, 2.5, 3.5]})
        self.assertEqual(catalog.harbor_check([5], 1), {'harbor_check': [5.0]})
        self.assertEqual(catalog.harbor_check([1, 2, 3], 3), {'harbor_check': [2.0]})
        self.assertEqual(catalog.harbor_check([2, 4, 6, 8, 10], 3), {'harbor_check': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            catalog.harbor_check([1, 2], 0)

    def test_payroll_sail_entry(self):
        self.assertEqual(payroll.sail_entry([1, 2, 3, 4], 2), {'sail_entry': [1.5, 2.5, 3.5]})
        self.assertEqual(payroll.sail_entry([5], 1), {'sail_entry': [5.0]})
        self.assertEqual(payroll.sail_entry([1, 2, 3], 3), {'sail_entry': [2.0]})
        self.assertEqual(payroll.sail_entry([2, 4, 6, 8, 10], 3), {'sail_entry': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            payroll.sail_entry([1, 2], 0)

    def test_old_name_gone(self):
        self.assertFalse(hasattr(routes, 'moving_average'))
        for f in [*pathlib.Path('lantern').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('moving_average', names(f.read_text(encoding="utf-8")), f)
