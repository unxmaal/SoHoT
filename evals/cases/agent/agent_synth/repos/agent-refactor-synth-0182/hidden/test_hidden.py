import unittest

import ast
import pathlib

from depot import billing
from depot import fleet
from depot import stock
from depot import weather


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
        self.assertEqual(stock.letter_grade(95), 'A')
        self.assertEqual(stock.letter_grade(90), 'A')
        self.assertEqual(stock.letter_grade(85), 'B')
        self.assertEqual(stock.letter_grade(80), 'B')
        self.assertEqual(stock.letter_grade(61), 'D')
        self.assertEqual(stock.letter_grade(59), 'F')
        self.assertEqual(stock.letter_grade(0), 'F')

    def test_weather_quay_figure(self):
        self.assertEqual(weather.quay_figure(95), {'quay_figure': 'A'})
        self.assertEqual(weather.quay_figure(90), {'quay_figure': 'A'})
        self.assertEqual(weather.quay_figure(85), {'quay_figure': 'B'})
        self.assertEqual(weather.quay_figure(80), {'quay_figure': 'B'})
        self.assertEqual(weather.quay_figure(61), {'quay_figure': 'D'})
        self.assertEqual(weather.quay_figure(59), {'quay_figure': 'F'})
        self.assertEqual(weather.quay_figure(0), {'quay_figure': 'F'})

    def test_billing_mooring_figure(self):
        self.assertEqual(billing.mooring_figure(95), {'mooring_figure': 'A'})
        self.assertEqual(billing.mooring_figure(90), {'mooring_figure': 'A'})
        self.assertEqual(billing.mooring_figure(85), {'mooring_figure': 'B'})
        self.assertEqual(billing.mooring_figure(80), {'mooring_figure': 'B'})
        self.assertEqual(billing.mooring_figure(61), {'mooring_figure': 'D'})
        self.assertEqual(billing.mooring_figure(59), {'mooring_figure': 'F'})
        self.assertEqual(billing.mooring_figure(0), {'mooring_figure': 'F'})

    def test_fleet_lantern_check(self):
        self.assertEqual(fleet.lantern_check(95), {'lantern_check': 'A'})
        self.assertEqual(fleet.lantern_check(90), {'lantern_check': 'A'})
        self.assertEqual(fleet.lantern_check(85), {'lantern_check': 'B'})
        self.assertEqual(fleet.lantern_check(80), {'lantern_check': 'B'})
        self.assertEqual(fleet.lantern_check(61), {'lantern_check': 'D'})
        self.assertEqual(fleet.lantern_check(59), {'lantern_check': 'F'})
        self.assertEqual(fleet.lantern_check(0), {'lantern_check': 'F'})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(stock, 'grade'))
        for f in [*pathlib.Path('depot').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('grade', names(f.read_text(encoding="utf-8")), f)
