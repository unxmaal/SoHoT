import unittest

import ast
import pathlib

from foundry import common
from foundry import orders
from foundry import sensors
from foundry import survey
from foundry import tickets


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
        self.assertEqual(common.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(common.luhn_valid('79927398713'), True)
        self.assertEqual(common.luhn_valid('79927398710'), False)
        self.assertEqual(common.luhn_valid(''), False)
        self.assertEqual(common.luhn_valid('059'), True)

    def test_tickets_pallet_entry(self):
        self.assertEqual(tickets.pallet_entry('4539 1488 0343 6467'), {'pallet_entry': True})
        self.assertEqual(tickets.pallet_entry('79927398713'), {'pallet_entry': True})
        self.assertEqual(tickets.pallet_entry('79927398710'), {'pallet_entry': False})
        self.assertEqual(tickets.pallet_entry(''), {'pallet_entry': False})
        self.assertEqual(tickets.pallet_entry('059'), {'pallet_entry': True})

    def test_sensors_tide_summary(self):
        self.assertEqual(sensors.tide_summary('4539 1488 0343 6467'), {'tide_summary': True})
        self.assertEqual(sensors.tide_summary('79927398713'), {'tide_summary': True})
        self.assertEqual(sensors.tide_summary('79927398710'), {'tide_summary': False})
        self.assertEqual(sensors.tide_summary(''), {'tide_summary': False})
        self.assertEqual(sensors.tide_summary('059'), {'tide_summary': True})

    def test_survey_mooring_entry(self):
        self.assertEqual(survey.mooring_entry('4539 1488 0343 6467'), {'mooring_entry': True})
        self.assertEqual(survey.mooring_entry('79927398713'), {'mooring_entry': True})
        self.assertEqual(survey.mooring_entry('79927398710'), {'mooring_entry': False})
        self.assertEqual(survey.mooring_entry(''), {'mooring_entry': False})
        self.assertEqual(survey.mooring_entry('059'), {'mooring_entry': True})

    def test_moved(self):
        new = pathlib.Path('foundry/common.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'luhn_valid' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('foundry/orders.py').read_text(encoding="utf-8")
        self.assertNotIn('luhn_valid', names(text))
