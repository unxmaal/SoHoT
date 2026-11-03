import unittest

import ast
import pathlib

from orchard import budget
from orchard import catalog
from orchard import fleet
from orchard import helpers
from orchard import payroll
from orchard import pricing


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
        self.assertEqual(helpers.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(helpers.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(helpers.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(helpers.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(helpers.bucket(7, []), 0)

    def test_catalog_rope_summary(self):
        self.assertEqual(catalog.rope_summary(5, [0, 5, 10]), {'rope_summary': 2})
        self.assertEqual(catalog.rope_summary(-1, [0, 5, 10]), {'rope_summary': 0})
        self.assertEqual(catalog.rope_summary(12, [0, 5, 10]), {'rope_summary': 3})
        self.assertEqual(catalog.rope_summary(0, [0, 5, 10]), {'rope_summary': 1})
        self.assertEqual(catalog.rope_summary(7, []), {'rope_summary': 0})

    def test_fleet_deck_total(self):
        self.assertEqual(fleet.deck_total(5, [0, 5, 10]), {'deck_total': 2})
        self.assertEqual(fleet.deck_total(-1, [0, 5, 10]), {'deck_total': 0})
        self.assertEqual(fleet.deck_total(12, [0, 5, 10]), {'deck_total': 3})
        self.assertEqual(fleet.deck_total(0, [0, 5, 10]), {'deck_total': 1})
        self.assertEqual(fleet.deck_total(7, []), {'deck_total': 0})

    def test_pricing_quay_row(self):
        self.assertEqual(pricing.quay_row(5, [0, 5, 10]), {'quay_row': 2})
        self.assertEqual(pricing.quay_row(-1, [0, 5, 10]), {'quay_row': 0})
        self.assertEqual(pricing.quay_row(12, [0, 5, 10]), {'quay_row': 3})
        self.assertEqual(pricing.quay_row(0, [0, 5, 10]), {'quay_row': 1})
        self.assertEqual(pricing.quay_row(7, []), {'quay_row': 0})

    def test_budget_rope_figure(self):
        self.assertEqual(budget.rope_figure(5, [0, 5, 10]), {'rope_figure': 2})
        self.assertEqual(budget.rope_figure(-1, [0, 5, 10]), {'rope_figure': 0})
        self.assertEqual(budget.rope_figure(12, [0, 5, 10]), {'rope_figure': 3})
        self.assertEqual(budget.rope_figure(0, [0, 5, 10]), {'rope_figure': 1})
        self.assertEqual(budget.rope_figure(7, []), {'rope_figure': 0})

    def test_moved(self):
        new = pathlib.Path('orchard/helpers.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'bucket' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('orchard/payroll.py').read_text(encoding="utf-8")
        self.assertNotIn('bucket', names(text))
