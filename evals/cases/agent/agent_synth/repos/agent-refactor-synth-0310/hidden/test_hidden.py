import unittest

import ast
import pathlib

from compass import kitchen
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
        self.assertEqual(kitchen.letter_grade(95), 'A')
        self.assertEqual(kitchen.letter_grade(90), 'A')
        self.assertEqual(kitchen.letter_grade(85), 'B')
        self.assertEqual(kitchen.letter_grade(80), 'B')
        self.assertEqual(kitchen.letter_grade(61), 'D')
        self.assertEqual(kitchen.letter_grade(59), 'F')
        self.assertEqual(kitchen.letter_grade(0), 'F')

    def test_rosters_sail_entry(self):
        self.assertEqual(rosters.sail_entry(95), {'sail_entry': 'A'})
        self.assertEqual(rosters.sail_entry(90), {'sail_entry': 'A'})
        self.assertEqual(rosters.sail_entry(85), {'sail_entry': 'B'})
        self.assertEqual(rosters.sail_entry(80), {'sail_entry': 'B'})
        self.assertEqual(rosters.sail_entry(61), {'sail_entry': 'D'})
        self.assertEqual(rosters.sail_entry(59), {'sail_entry': 'F'})
        self.assertEqual(rosters.sail_entry(0), {'sail_entry': 'F'})

    def test_sensors_deck_view(self):
        self.assertEqual(sensors.deck_view(95), {'deck_view': 'A'})
        self.assertEqual(sensors.deck_view(90), {'deck_view': 'A'})
        self.assertEqual(sensors.deck_view(85), {'deck_view': 'B'})
        self.assertEqual(sensors.deck_view(80), {'deck_view': 'B'})
        self.assertEqual(sensors.deck_view(61), {'deck_view': 'D'})
        self.assertEqual(sensors.deck_view(59), {'deck_view': 'F'})
        self.assertEqual(sensors.deck_view(0), {'deck_view': 'F'})

    def test_timesheet_anchor_row(self):
        self.assertEqual(timesheet.anchor_row(95), {'anchor_row': 'A'})
        self.assertEqual(timesheet.anchor_row(90), {'anchor_row': 'A'})
        self.assertEqual(timesheet.anchor_row(85), {'anchor_row': 'B'})
        self.assertEqual(timesheet.anchor_row(80), {'anchor_row': 'B'})
        self.assertEqual(timesheet.anchor_row(61), {'anchor_row': 'D'})
        self.assertEqual(timesheet.anchor_row(59), {'anchor_row': 'F'})
        self.assertEqual(timesheet.anchor_row(0), {'anchor_row': 'F'})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(kitchen, 'grade'))
        for f in [*pathlib.Path('compass').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('grade', names(f.read_text(encoding="utf-8")), f)
