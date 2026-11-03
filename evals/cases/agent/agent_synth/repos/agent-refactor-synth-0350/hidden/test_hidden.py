import unittest

import ast
import pathlib

from wharf import stock
from wharf import survey
from wharf import timesheet


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
        self.assertEqual(survey.midpoint([3, 1, 2]), 2)
        self.assertEqual(survey.midpoint([4, 1, 3, 2]), 2.5)
        self.assertEqual(survey.midpoint([5]), 5)
        self.assertEqual(survey.midpoint([1, 2]), 1.5)
        self.assertEqual(survey.midpoint([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            survey.midpoint([])

    def test_timesheet_buoy_total(self):
        self.assertEqual(timesheet.buoy_total([3, 1, 2]), {'buoy_total': 2})
        self.assertEqual(timesheet.buoy_total([4, 1, 3, 2]), {'buoy_total': 2.5})
        self.assertEqual(timesheet.buoy_total([5]), {'buoy_total': 5})
        self.assertEqual(timesheet.buoy_total([1, 2]), {'buoy_total': 1.5})
        self.assertEqual(timesheet.buoy_total([10, 2, 38, 23, 38, 23]), {'buoy_total': 23.0})
        with self.assertRaises(ValueError):
            timesheet.buoy_total([])

    def test_stock_deck_figure(self):
        self.assertEqual(stock.deck_figure([3, 1, 2]), {'deck_figure': 2})
        self.assertEqual(stock.deck_figure([4, 1, 3, 2]), {'deck_figure': 2.5})
        self.assertEqual(stock.deck_figure([5]), {'deck_figure': 5})
        self.assertEqual(stock.deck_figure([1, 2]), {'deck_figure': 1.5})
        self.assertEqual(stock.deck_figure([10, 2, 38, 23, 38, 23]), {'deck_figure': 23.0})
        with self.assertRaises(ValueError):
            stock.deck_figure([])

    def test_old_name_gone(self):
        self.assertFalse(hasattr(survey, 'median'))
        for f in [*pathlib.Path('wharf').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('median', names(f.read_text(encoding="utf-8")), f)
