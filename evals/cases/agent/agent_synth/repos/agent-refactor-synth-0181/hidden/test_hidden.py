import unittest

import ast
import pathlib

from harbor import catalog
from harbor import common
from harbor import ledger
from harbor import sensors
from harbor import timesheet


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
        self.assertEqual(common.grade(95), 'A')
        self.assertEqual(common.grade(90), 'A')
        self.assertEqual(common.grade(85), 'B')
        self.assertEqual(common.grade(80), 'B')
        self.assertEqual(common.grade(61), 'D')
        self.assertEqual(common.grade(59), 'F')
        self.assertEqual(common.grade(0), 'F')

    def test_timesheet_pallet_entry(self):
        self.assertEqual(timesheet.pallet_entry(95), {'pallet_entry': 'A'})
        self.assertEqual(timesheet.pallet_entry(90), {'pallet_entry': 'A'})
        self.assertEqual(timesheet.pallet_entry(85), {'pallet_entry': 'B'})
        self.assertEqual(timesheet.pallet_entry(80), {'pallet_entry': 'B'})
        self.assertEqual(timesheet.pallet_entry(61), {'pallet_entry': 'D'})
        self.assertEqual(timesheet.pallet_entry(59), {'pallet_entry': 'F'})
        self.assertEqual(timesheet.pallet_entry(0), {'pallet_entry': 'F'})

    def test_sensors_mooring_check(self):
        self.assertEqual(sensors.mooring_check(95), {'mooring_check': 'A'})
        self.assertEqual(sensors.mooring_check(90), {'mooring_check': 'A'})
        self.assertEqual(sensors.mooring_check(85), {'mooring_check': 'B'})
        self.assertEqual(sensors.mooring_check(80), {'mooring_check': 'B'})
        self.assertEqual(sensors.mooring_check(61), {'mooring_check': 'D'})
        self.assertEqual(sensors.mooring_check(59), {'mooring_check': 'F'})
        self.assertEqual(sensors.mooring_check(0), {'mooring_check': 'F'})

    def test_ledger_cargo_row(self):
        self.assertEqual(ledger.cargo_row(95), {'cargo_row': 'A'})
        self.assertEqual(ledger.cargo_row(90), {'cargo_row': 'A'})
        self.assertEqual(ledger.cargo_row(85), {'cargo_row': 'B'})
        self.assertEqual(ledger.cargo_row(80), {'cargo_row': 'B'})
        self.assertEqual(ledger.cargo_row(61), {'cargo_row': 'D'})
        self.assertEqual(ledger.cargo_row(59), {'cargo_row': 'F'})
        self.assertEqual(ledger.cargo_row(0), {'cargo_row': 'F'})

    def test_moved(self):
        new = pathlib.Path('harbor/common.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'grade' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('harbor/catalog.py').read_text(encoding="utf-8")
        self.assertNotIn('grade', names(text))
