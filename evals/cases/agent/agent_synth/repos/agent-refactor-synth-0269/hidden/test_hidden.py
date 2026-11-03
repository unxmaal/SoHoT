import unittest

import ast
import pathlib

from kiln import catalog
from kiln import fleet
from kiln import rosters
from kiln import sensors
from kiln import timesheet
from kiln import tools


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

    def test_catalog_hull_total(self):
        self.assertEqual(catalog.hull_total(5, [0, 5, 10]), {'hull_total': 2})
        self.assertEqual(catalog.hull_total(-1, [0, 5, 10]), {'hull_total': 0})
        self.assertEqual(catalog.hull_total(12, [0, 5, 10]), {'hull_total': 3})
        self.assertEqual(catalog.hull_total(0, [0, 5, 10]), {'hull_total': 1})
        self.assertEqual(catalog.hull_total(7, []), {'hull_total': 0})

    def test_timesheet_ferry_figure(self):
        self.assertEqual(timesheet.ferry_figure(5, [0, 5, 10]), {'ferry_figure': 2})
        self.assertEqual(timesheet.ferry_figure(-1, [0, 5, 10]), {'ferry_figure': 0})
        self.assertEqual(timesheet.ferry_figure(12, [0, 5, 10]), {'ferry_figure': 3})
        self.assertEqual(timesheet.ferry_figure(0, [0, 5, 10]), {'ferry_figure': 1})
        self.assertEqual(timesheet.ferry_figure(7, []), {'ferry_figure': 0})

    def test_sensors_harbor_check(self):
        self.assertEqual(sensors.harbor_check(5, [0, 5, 10]), {'harbor_check': 2})
        self.assertEqual(sensors.harbor_check(-1, [0, 5, 10]), {'harbor_check': 0})
        self.assertEqual(sensors.harbor_check(12, [0, 5, 10]), {'harbor_check': 3})
        self.assertEqual(sensors.harbor_check(0, [0, 5, 10]), {'harbor_check': 1})
        self.assertEqual(sensors.harbor_check(7, []), {'harbor_check': 0})

    def test_rosters_buoy_view(self):
        self.assertEqual(rosters.buoy_view(5, [0, 5, 10]), {'buoy_view': 2})
        self.assertEqual(rosters.buoy_view(-1, [0, 5, 10]), {'buoy_view': 0})
        self.assertEqual(rosters.buoy_view(12, [0, 5, 10]), {'buoy_view': 3})
        self.assertEqual(rosters.buoy_view(0, [0, 5, 10]), {'buoy_view': 1})
        self.assertEqual(rosters.buoy_view(7, []), {'buoy_view': 0})

    def test_moved(self):
        new = pathlib.Path('kiln/tools.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'bucket' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('kiln/fleet.py').read_text(encoding="utf-8")
        self.assertNotIn('bucket', names(text))
