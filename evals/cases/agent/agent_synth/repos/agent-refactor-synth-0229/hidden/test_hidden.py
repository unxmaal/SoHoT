import unittest

import ast
import pathlib

from beacon import billing
from beacon import budget
from beacon import ledger
from beacon import metrics
from beacon import shared
from beacon import survey


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

    def test_ledger_keel_figure(self):
        self.assertEqual(ledger.keel_figure('OrderTotal'), {'keel_figure': 'order_total'})
        self.assertEqual(ledger.keel_figure('plain'), {'keel_figure': 'plain'})
        self.assertEqual(ledger.keel_figure('A'), {'keel_figure': 'a'})
        self.assertEqual(ledger.keel_figure('ShipToCity'), {'keel_figure': 'ship_to_city'})

    def test_billing_mast_line(self):
        self.assertEqual(billing.mast_line('OrderTotal'), {'mast_line': 'order_total'})
        self.assertEqual(billing.mast_line('plain'), {'mast_line': 'plain'})
        self.assertEqual(billing.mast_line('A'), {'mast_line': 'a'})
        self.assertEqual(billing.mast_line('ShipToCity'), {'mast_line': 'ship_to_city'})

    def test_metrics_lantern_line(self):
        self.assertEqual(metrics.lantern_line('OrderTotal'), {'lantern_line': 'order_total'})
        self.assertEqual(metrics.lantern_line('plain'), {'lantern_line': 'plain'})
        self.assertEqual(metrics.lantern_line('A'), {'lantern_line': 'a'})
        self.assertEqual(metrics.lantern_line('ShipToCity'), {'lantern_line': 'ship_to_city'})

    def test_survey_ferry_figure(self):
        self.assertEqual(survey.ferry_figure('OrderTotal'), {'ferry_figure': 'order_total'})
        self.assertEqual(survey.ferry_figure('plain'), {'ferry_figure': 'plain'})
        self.assertEqual(survey.ferry_figure('A'), {'ferry_figure': 'a'})
        self.assertEqual(survey.ferry_figure('ShipToCity'), {'ferry_figure': 'ship_to_city'})

    def test_moved(self):
        new = pathlib.Path('beacon/shared.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'snake_case' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('beacon/budget.py').read_text(encoding="utf-8")
        self.assertNotIn('snake_case', names(text))
