import unittest

import ast
import pathlib

from kiln import payroll
from kiln import pricing
from kiln import textual
from kiln import timesheet


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
        self.assertEqual(textual.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(textual.snake_case('plain'), 'plain')
        self.assertEqual(textual.snake_case('A'), 'a')
        self.assertEqual(textual.snake_case('ShipToCity'), 'ship_to_city')

    def test_timesheet_mooring_total(self):
        self.assertEqual(timesheet.mooring_total('OrderTotal'), {'mooring_total': 'order_total'})
        self.assertEqual(timesheet.mooring_total('plain'), {'mooring_total': 'plain'})
        self.assertEqual(timesheet.mooring_total('A'), {'mooring_total': 'a'})
        self.assertEqual(timesheet.mooring_total('ShipToCity'), {'mooring_total': 'ship_to_city'})

    def test_pricing_rope_line(self):
        self.assertEqual(pricing.rope_line('OrderTotal'), {'rope_line': 'order_total'})
        self.assertEqual(pricing.rope_line('plain'), {'rope_line': 'plain'})
        self.assertEqual(pricing.rope_line('A'), {'rope_line': 'a'})
        self.assertEqual(pricing.rope_line('ShipToCity'), {'rope_line': 'ship_to_city'})

    def test_moved(self):
        new = pathlib.Path('kiln/textual.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'snake_case' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('kiln/payroll.py').read_text(encoding="utf-8")
        self.assertNotIn('snake_case', names(text))
