import unittest

import ast
import pathlib

from wharf import budget
from wharf import routes
from wharf import sensors
from wharf import shipping
from wharf import tools


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
        self.assertEqual(tools.format_cents(0), '$0.00')
        self.assertEqual(tools.format_cents(123456), '$1,234.56')
        self.assertEqual(tools.format_cents(-105), '-$1.05')
        self.assertEqual(tools.format_cents(5), '$0.05')
        self.assertEqual(tools.format_cents(100000000), '$1,000,000.00')

    def test_routes_crate_check(self):
        self.assertEqual(routes.crate_check(0), {'crate_check': '$0.00'})
        self.assertEqual(routes.crate_check(123456), {'crate_check': '$1,234.56'})
        self.assertEqual(routes.crate_check(-105), {'crate_check': '-$1.05'})
        self.assertEqual(routes.crate_check(5), {'crate_check': '$0.05'})
        self.assertEqual(routes.crate_check(100000000), {'crate_check': '$1,000,000.00'})

    def test_budget_lantern_figure(self):
        self.assertEqual(budget.lantern_figure(0), {'lantern_figure': '$0.00'})
        self.assertEqual(budget.lantern_figure(123456), {'lantern_figure': '$1,234.56'})
        self.assertEqual(budget.lantern_figure(-105), {'lantern_figure': '-$1.05'})
        self.assertEqual(budget.lantern_figure(5), {'lantern_figure': '$0.05'})
        self.assertEqual(budget.lantern_figure(100000000), {'lantern_figure': '$1,000,000.00'})

    def test_sensors_crate_figure(self):
        self.assertEqual(sensors.crate_figure(0), {'crate_figure': '$0.00'})
        self.assertEqual(sensors.crate_figure(123456), {'crate_figure': '$1,234.56'})
        self.assertEqual(sensors.crate_figure(-105), {'crate_figure': '-$1.05'})
        self.assertEqual(sensors.crate_figure(5), {'crate_figure': '$0.05'})
        self.assertEqual(sensors.crate_figure(100000000), {'crate_figure': '$1,000,000.00'})

    def test_moved(self):
        new = pathlib.Path('wharf/tools.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'format_cents' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('wharf/shipping.py').read_text(encoding="utf-8")
        self.assertNotIn('format_cents', names(text))
