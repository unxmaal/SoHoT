import unittest

import ast
import pathlib

from granary import archive
from granary import kitchen
from granary import orders
from granary import shared
from granary import tickets


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
        self.assertEqual(shared.grade(95), 'A')
        self.assertEqual(shared.grade(90), 'A')
        self.assertEqual(shared.grade(85), 'B')
        self.assertEqual(shared.grade(80), 'B')
        self.assertEqual(shared.grade(61), 'D')
        self.assertEqual(shared.grade(59), 'F')
        self.assertEqual(shared.grade(0), 'F')

    def test_tickets_ferry_figure(self):
        self.assertEqual(tickets.ferry_figure(95), {'ferry_figure': 'A'})
        self.assertEqual(tickets.ferry_figure(90), {'ferry_figure': 'A'})
        self.assertEqual(tickets.ferry_figure(85), {'ferry_figure': 'B'})
        self.assertEqual(tickets.ferry_figure(80), {'ferry_figure': 'B'})
        self.assertEqual(tickets.ferry_figure(61), {'ferry_figure': 'D'})
        self.assertEqual(tickets.ferry_figure(59), {'ferry_figure': 'F'})
        self.assertEqual(tickets.ferry_figure(0), {'ferry_figure': 'F'})

    def test_kitchen_sail_row(self):
        self.assertEqual(kitchen.sail_row(95), {'sail_row': 'A'})
        self.assertEqual(kitchen.sail_row(90), {'sail_row': 'A'})
        self.assertEqual(kitchen.sail_row(85), {'sail_row': 'B'})
        self.assertEqual(kitchen.sail_row(80), {'sail_row': 'B'})
        self.assertEqual(kitchen.sail_row(61), {'sail_row': 'D'})
        self.assertEqual(kitchen.sail_row(59), {'sail_row': 'F'})
        self.assertEqual(kitchen.sail_row(0), {'sail_row': 'F'})

    def test_orders_ferry_figure(self):
        self.assertEqual(orders.ferry_figure(95), {'ferry_figure': 'A'})
        self.assertEqual(orders.ferry_figure(90), {'ferry_figure': 'A'})
        self.assertEqual(orders.ferry_figure(85), {'ferry_figure': 'B'})
        self.assertEqual(orders.ferry_figure(80), {'ferry_figure': 'B'})
        self.assertEqual(orders.ferry_figure(61), {'ferry_figure': 'D'})
        self.assertEqual(orders.ferry_figure(59), {'ferry_figure': 'F'})
        self.assertEqual(orders.ferry_figure(0), {'ferry_figure': 'F'})

    def test_moved(self):
        new = pathlib.Path('granary/shared.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'grade' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('granary/archive.py').read_text(encoding="utf-8")
        self.assertNotIn('grade', names(text))
