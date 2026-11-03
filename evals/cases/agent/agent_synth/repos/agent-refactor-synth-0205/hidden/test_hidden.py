import unittest

import ast
import pathlib

from tally import budget
from tally import common
from tally import fleet
from tally import kitchen
from tally import ledger


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
        self.assertEqual(common.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(common.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(common.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(common.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(common.bucket(7, []), 0)

    def test_budget_rope_row(self):
        self.assertEqual(budget.rope_row(5, [0, 5, 10]), {'rope_row': 2})
        self.assertEqual(budget.rope_row(-1, [0, 5, 10]), {'rope_row': 0})
        self.assertEqual(budget.rope_row(12, [0, 5, 10]), {'rope_row': 3})
        self.assertEqual(budget.rope_row(0, [0, 5, 10]), {'rope_row': 1})
        self.assertEqual(budget.rope_row(7, []), {'rope_row': 0})

    def test_ledger_cargo_figure(self):
        self.assertEqual(ledger.cargo_figure(5, [0, 5, 10]), {'cargo_figure': 2})
        self.assertEqual(ledger.cargo_figure(-1, [0, 5, 10]), {'cargo_figure': 0})
        self.assertEqual(ledger.cargo_figure(12, [0, 5, 10]), {'cargo_figure': 3})
        self.assertEqual(ledger.cargo_figure(0, [0, 5, 10]), {'cargo_figure': 1})
        self.assertEqual(ledger.cargo_figure(7, []), {'cargo_figure': 0})

    def test_fleet_tide_entry(self):
        self.assertEqual(fleet.tide_entry(5, [0, 5, 10]), {'tide_entry': 2})
        self.assertEqual(fleet.tide_entry(-1, [0, 5, 10]), {'tide_entry': 0})
        self.assertEqual(fleet.tide_entry(12, [0, 5, 10]), {'tide_entry': 3})
        self.assertEqual(fleet.tide_entry(0, [0, 5, 10]), {'tide_entry': 1})
        self.assertEqual(fleet.tide_entry(7, []), {'tide_entry': 0})

    def test_moved(self):
        new = pathlib.Path('tally/common.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'bucket' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('tally/kitchen.py').read_text(encoding="utf-8")
        self.assertNotIn('bucket', names(text))
