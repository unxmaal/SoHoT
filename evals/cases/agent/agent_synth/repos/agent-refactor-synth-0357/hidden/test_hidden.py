import unittest

import ast
import pathlib

from granary import archive
from granary import billing
from granary import ledger
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
        self.assertEqual(shared.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(shared.snake_case('plain'), 'plain')
        self.assertEqual(shared.snake_case('A'), 'a')
        self.assertEqual(shared.snake_case('ShipToCity'), 'ship_to_city')

    def test_tickets_lantern_total(self):
        self.assertEqual(tickets.lantern_total('OrderTotal'), {'lantern_total': 'order_total'})
        self.assertEqual(tickets.lantern_total('plain'), {'lantern_total': 'plain'})
        self.assertEqual(tickets.lantern_total('A'), {'lantern_total': 'a'})
        self.assertEqual(tickets.lantern_total('ShipToCity'), {'lantern_total': 'ship_to_city'})

    def test_billing_ferry_line(self):
        self.assertEqual(billing.ferry_line('OrderTotal'), {'ferry_line': 'order_total'})
        self.assertEqual(billing.ferry_line('plain'), {'ferry_line': 'plain'})
        self.assertEqual(billing.ferry_line('A'), {'ferry_line': 'a'})
        self.assertEqual(billing.ferry_line('ShipToCity'), {'ferry_line': 'ship_to_city'})

    def test_archive_dock_row(self):
        self.assertEqual(archive.dock_row('OrderTotal'), {'dock_row': 'order_total'})
        self.assertEqual(archive.dock_row('plain'), {'dock_row': 'plain'})
        self.assertEqual(archive.dock_row('A'), {'dock_row': 'a'})
        self.assertEqual(archive.dock_row('ShipToCity'), {'dock_row': 'ship_to_city'})

    def test_orders_anchor_row(self):
        self.assertEqual(orders.anchor_row('OrderTotal'), {'anchor_row': 'order_total'})
        self.assertEqual(orders.anchor_row('plain'), {'anchor_row': 'plain'})
        self.assertEqual(orders.anchor_row('A'), {'anchor_row': 'a'})
        self.assertEqual(orders.anchor_row('ShipToCity'), {'anchor_row': 'ship_to_city'})

    def test_moved(self):
        new = pathlib.Path('granary/shared.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'snake_case' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('granary/ledger.py').read_text(encoding="utf-8")
        self.assertNotIn('snake_case', names(text))
