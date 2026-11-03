import unittest

import ast
import pathlib

from quarry import billing
from quarry import budget
from quarry import kitchen
from quarry import shared
from quarry import timesheet
from quarry import weather


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
        self.assertEqual(shared.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(shared.luhn_valid('79927398713'), True)
        self.assertEqual(shared.luhn_valid('79927398710'), False)
        self.assertEqual(shared.luhn_valid(''), False)
        self.assertEqual(shared.luhn_valid('059'), True)

    def test_kitchen_sail_entry(self):
        self.assertEqual(kitchen.sail_entry('4539 1488 0343 6467'), {'sail_entry': True})
        self.assertEqual(kitchen.sail_entry('79927398713'), {'sail_entry': True})
        self.assertEqual(kitchen.sail_entry('79927398710'), {'sail_entry': False})
        self.assertEqual(kitchen.sail_entry(''), {'sail_entry': False})
        self.assertEqual(kitchen.sail_entry('059'), {'sail_entry': True})

    def test_timesheet_quay_view(self):
        self.assertEqual(timesheet.quay_view('4539 1488 0343 6467'), {'quay_view': True})
        self.assertEqual(timesheet.quay_view('79927398713'), {'quay_view': True})
        self.assertEqual(timesheet.quay_view('79927398710'), {'quay_view': False})
        self.assertEqual(timesheet.quay_view(''), {'quay_view': False})
        self.assertEqual(timesheet.quay_view('059'), {'quay_view': True})

    def test_weather_ferry_figure(self):
        self.assertEqual(weather.ferry_figure('4539 1488 0343 6467'), {'ferry_figure': True})
        self.assertEqual(weather.ferry_figure('79927398713'), {'ferry_figure': True})
        self.assertEqual(weather.ferry_figure('79927398710'), {'ferry_figure': False})
        self.assertEqual(weather.ferry_figure(''), {'ferry_figure': False})
        self.assertEqual(weather.ferry_figure('059'), {'ferry_figure': True})

    def test_billing_berth_row(self):
        self.assertEqual(billing.berth_row('4539 1488 0343 6467'), {'berth_row': True})
        self.assertEqual(billing.berth_row('79927398713'), {'berth_row': True})
        self.assertEqual(billing.berth_row('79927398710'), {'berth_row': False})
        self.assertEqual(billing.berth_row(''), {'berth_row': False})
        self.assertEqual(billing.berth_row('059'), {'berth_row': True})

    def test_moved(self):
        new = pathlib.Path('quarry/shared.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'luhn_valid' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('quarry/budget.py').read_text(encoding="utf-8")
        self.assertNotIn('luhn_valid', names(text))
