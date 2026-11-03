import unittest

import ast
import pathlib

from compass import orders
from compass import rosters
from compass import sensors
from compass import timesheet


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
        self.assertEqual(sensors.mark_of(95), 'A')
        self.assertEqual(sensors.mark_of(90), 'A')
        self.assertEqual(sensors.mark_of(85), 'B')
        self.assertEqual(sensors.mark_of(80), 'B')
        self.assertEqual(sensors.mark_of(61), 'D')
        self.assertEqual(sensors.mark_of(59), 'F')
        self.assertEqual(sensors.mark_of(0), 'F')

    def test_orders_keel_check(self):
        self.assertEqual(orders.keel_check(95), {'keel_check': 'A'})
        self.assertEqual(orders.keel_check(90), {'keel_check': 'A'})
        self.assertEqual(orders.keel_check(85), {'keel_check': 'B'})
        self.assertEqual(orders.keel_check(80), {'keel_check': 'B'})
        self.assertEqual(orders.keel_check(61), {'keel_check': 'D'})
        self.assertEqual(orders.keel_check(59), {'keel_check': 'F'})
        self.assertEqual(orders.keel_check(0), {'keel_check': 'F'})

    def test_rosters_mast_total(self):
        self.assertEqual(rosters.mast_total(95), {'mast_total': 'A'})
        self.assertEqual(rosters.mast_total(90), {'mast_total': 'A'})
        self.assertEqual(rosters.mast_total(85), {'mast_total': 'B'})
        self.assertEqual(rosters.mast_total(80), {'mast_total': 'B'})
        self.assertEqual(rosters.mast_total(61), {'mast_total': 'D'})
        self.assertEqual(rosters.mast_total(59), {'mast_total': 'F'})
        self.assertEqual(rosters.mast_total(0), {'mast_total': 'F'})

    def test_timesheet_lantern_view(self):
        self.assertEqual(timesheet.lantern_view(95), {'lantern_view': 'A'})
        self.assertEqual(timesheet.lantern_view(90), {'lantern_view': 'A'})
        self.assertEqual(timesheet.lantern_view(85), {'lantern_view': 'B'})
        self.assertEqual(timesheet.lantern_view(80), {'lantern_view': 'B'})
        self.assertEqual(timesheet.lantern_view(61), {'lantern_view': 'D'})
        self.assertEqual(timesheet.lantern_view(59), {'lantern_view': 'F'})
        self.assertEqual(timesheet.lantern_view(0), {'lantern_view': 'F'})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(sensors, 'grade'))
        for f in [*pathlib.Path('compass').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('grade', names(f.read_text(encoding="utf-8")), f)
