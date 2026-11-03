import unittest

import ast
import pathlib

from mill import payroll
from mill import sensors
from mill import toolkit
from mill import weather


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
        self.assertEqual(toolkit.format_cents(0), '$0.00')
        self.assertEqual(toolkit.format_cents(123456), '$1,234.56')
        self.assertEqual(toolkit.format_cents(-105), '-$1.05')
        self.assertEqual(toolkit.format_cents(5), '$0.05')
        self.assertEqual(toolkit.format_cents(100000000), '$1,000,000.00')

    def test_sensors_ferry_summary(self):
        self.assertEqual(sensors.ferry_summary(0), {'ferry_summary': '$0.00'})
        self.assertEqual(sensors.ferry_summary(123456), {'ferry_summary': '$1,234.56'})
        self.assertEqual(sensors.ferry_summary(-105), {'ferry_summary': '-$1.05'})
        self.assertEqual(sensors.ferry_summary(5), {'ferry_summary': '$0.05'})
        self.assertEqual(sensors.ferry_summary(100000000), {'ferry_summary': '$1,000,000.00'})

    def test_weather_cargo_row(self):
        self.assertEqual(weather.cargo_row(0), {'cargo_row': '$0.00'})
        self.assertEqual(weather.cargo_row(123456), {'cargo_row': '$1,234.56'})
        self.assertEqual(weather.cargo_row(-105), {'cargo_row': '-$1.05'})
        self.assertEqual(weather.cargo_row(5), {'cargo_row': '$0.05'})
        self.assertEqual(weather.cargo_row(100000000), {'cargo_row': '$1,000,000.00'})

    def test_moved(self):
        new = pathlib.Path('mill/toolkit.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'format_cents' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('mill/payroll.py').read_text(encoding="utf-8")
        self.assertNotIn('format_cents', names(text))
