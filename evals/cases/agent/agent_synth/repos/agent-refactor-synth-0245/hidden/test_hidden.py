import unittest

import ast
import pathlib

from foundry import pricing
from foundry import routes
from foundry import sensors
from foundry import timesheet
from foundry import tools


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
        self.assertEqual(tools.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(tools.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(tools.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(tools.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(tools.bucket(7, []), 0)

    def test_pricing_sail_total(self):
        self.assertEqual(pricing.sail_total(5, [0, 5, 10]), {'sail_total': 2})
        self.assertEqual(pricing.sail_total(-1, [0, 5, 10]), {'sail_total': 0})
        self.assertEqual(pricing.sail_total(12, [0, 5, 10]), {'sail_total': 3})
        self.assertEqual(pricing.sail_total(0, [0, 5, 10]), {'sail_total': 1})
        self.assertEqual(pricing.sail_total(7, []), {'sail_total': 0})

    def test_timesheet_mast_entry(self):
        self.assertEqual(timesheet.mast_entry(5, [0, 5, 10]), {'mast_entry': 2})
        self.assertEqual(timesheet.mast_entry(-1, [0, 5, 10]), {'mast_entry': 0})
        self.assertEqual(timesheet.mast_entry(12, [0, 5, 10]), {'mast_entry': 3})
        self.assertEqual(timesheet.mast_entry(0, [0, 5, 10]), {'mast_entry': 1})
        self.assertEqual(timesheet.mast_entry(7, []), {'mast_entry': 0})

    def test_sensors_mooring_summary(self):
        self.assertEqual(sensors.mooring_summary(5, [0, 5, 10]), {'mooring_summary': 2})
        self.assertEqual(sensors.mooring_summary(-1, [0, 5, 10]), {'mooring_summary': 0})
        self.assertEqual(sensors.mooring_summary(12, [0, 5, 10]), {'mooring_summary': 3})
        self.assertEqual(sensors.mooring_summary(0, [0, 5, 10]), {'mooring_summary': 1})
        self.assertEqual(sensors.mooring_summary(7, []), {'mooring_summary': 0})

    def test_moved(self):
        new = pathlib.Path('foundry/tools.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'bucket' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('foundry/routes.py').read_text(encoding="utf-8")
        self.assertNotIn('bucket', names(text))
