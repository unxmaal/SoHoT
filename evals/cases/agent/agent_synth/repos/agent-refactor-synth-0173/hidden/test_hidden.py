import unittest

import ast
import pathlib

from tally import helpers
from tally import kitchen
from tally import ledger
from tally import orders
from tally import stock
from tally import survey


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
        self.assertEqual(helpers.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(helpers.snake_case('plain'), 'plain')
        self.assertEqual(helpers.snake_case('A'), 'a')
        self.assertEqual(helpers.snake_case('ShipToCity'), 'ship_to_city')

    def test_survey_tide_summary(self):
        self.assertEqual(survey.tide_summary('OrderTotal'), {'tide_summary': 'order_total'})
        self.assertEqual(survey.tide_summary('plain'), {'tide_summary': 'plain'})
        self.assertEqual(survey.tide_summary('A'), {'tide_summary': 'a'})
        self.assertEqual(survey.tide_summary('ShipToCity'), {'tide_summary': 'ship_to_city'})

    def test_kitchen_dock_entry(self):
        self.assertEqual(kitchen.dock_entry('OrderTotal'), {'dock_entry': 'order_total'})
        self.assertEqual(kitchen.dock_entry('plain'), {'dock_entry': 'plain'})
        self.assertEqual(kitchen.dock_entry('A'), {'dock_entry': 'a'})
        self.assertEqual(kitchen.dock_entry('ShipToCity'), {'dock_entry': 'ship_to_city'})

    def test_orders_harbor_check(self):
        self.assertEqual(orders.harbor_check('OrderTotal'), {'harbor_check': 'order_total'})
        self.assertEqual(orders.harbor_check('plain'), {'harbor_check': 'plain'})
        self.assertEqual(orders.harbor_check('A'), {'harbor_check': 'a'})
        self.assertEqual(orders.harbor_check('ShipToCity'), {'harbor_check': 'ship_to_city'})

    def test_stock_deck_check(self):
        self.assertEqual(stock.deck_check('OrderTotal'), {'deck_check': 'order_total'})
        self.assertEqual(stock.deck_check('plain'), {'deck_check': 'plain'})
        self.assertEqual(stock.deck_check('A'), {'deck_check': 'a'})
        self.assertEqual(stock.deck_check('ShipToCity'), {'deck_check': 'ship_to_city'})

    def test_moved(self):
        new = pathlib.Path('tally/helpers.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'snake_case' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('tally/ledger.py').read_text(encoding="utf-8")
        self.assertNotIn('snake_case', names(text))
