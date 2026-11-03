import unittest

import ast
import pathlib

from wharf import rosters
from wharf import sensors
from wharf import tools
from wharf import weather


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
        self.assertEqual(tools.percent_change(50, 75), 50.0)
        self.assertEqual(tools.percent_change(200, 150), -25.0)
        self.assertEqual(tools.percent_change(80, 80), 0.0)
        self.assertEqual(tools.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            tools.percent_change(0, 5)
        self.assertEqual(tools.percent_change(-10, -5), -50.0)

    def test_weather_pallet_row(self):
        self.assertEqual(weather.pallet_row(50, 75), {'pallet_row': 50.0})
        self.assertEqual(weather.pallet_row(200, 150), {'pallet_row': -25.0})
        self.assertEqual(weather.pallet_row(80, 80), {'pallet_row': 0.0})
        self.assertEqual(weather.pallet_row(3, 4), {'pallet_row': 33.33})
        with self.assertRaises(ValueError):
            weather.pallet_row(0, 5)
        self.assertEqual(weather.pallet_row(-10, -5), {'pallet_row': -50.0})

    def test_sensors_sail_row(self):
        self.assertEqual(sensors.sail_row(50, 75), {'sail_row': 50.0})
        self.assertEqual(sensors.sail_row(200, 150), {'sail_row': -25.0})
        self.assertEqual(sensors.sail_row(80, 80), {'sail_row': 0.0})
        self.assertEqual(sensors.sail_row(3, 4), {'sail_row': 33.33})
        with self.assertRaises(ValueError):
            sensors.sail_row(0, 5)
        self.assertEqual(sensors.sail_row(-10, -5), {'sail_row': -50.0})

    def test_moved(self):
        new = pathlib.Path('wharf/tools.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'percent_change' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('wharf/rosters.py').read_text(encoding="utf-8")
        self.assertNotIn('percent_change', names(text))
