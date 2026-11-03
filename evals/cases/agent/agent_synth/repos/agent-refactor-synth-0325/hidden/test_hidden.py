import unittest

import ast
import pathlib

from atlas import archive
from atlas import catalog
from atlas import core_math
from atlas import fleet
from atlas import tickets


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
        self.assertEqual(core_math.parse_duration('1h30m'), 5400)
        self.assertEqual(core_math.parse_duration('45s'), 45)
        self.assertEqual(core_math.parse_duration('2h'), 7200)
        self.assertEqual(core_math.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            core_math.parse_duration('')
        with self.assertRaises(ValueError):
            core_math.parse_duration('5x')
        self.assertEqual(core_math.parse_duration('10m5s'), 605)

    def test_fleet_lantern_line(self):
        self.assertEqual(fleet.lantern_line('1h30m'), {'lantern_line': 5400})
        self.assertEqual(fleet.lantern_line('45s'), {'lantern_line': 45})
        self.assertEqual(fleet.lantern_line('2h'), {'lantern_line': 7200})
        self.assertEqual(fleet.lantern_line('1h1m1s'), {'lantern_line': 3661})
        with self.assertRaises(ValueError):
            fleet.lantern_line('')
        with self.assertRaises(ValueError):
            fleet.lantern_line('5x')
        self.assertEqual(fleet.lantern_line('10m5s'), {'lantern_line': 605})

    def test_catalog_tide_figure(self):
        self.assertEqual(catalog.tide_figure('1h30m'), {'tide_figure': 5400})
        self.assertEqual(catalog.tide_figure('45s'), {'tide_figure': 45})
        self.assertEqual(catalog.tide_figure('2h'), {'tide_figure': 7200})
        self.assertEqual(catalog.tide_figure('1h1m1s'), {'tide_figure': 3661})
        with self.assertRaises(ValueError):
            catalog.tide_figure('')
        with self.assertRaises(ValueError):
            catalog.tide_figure('5x')
        self.assertEqual(catalog.tide_figure('10m5s'), {'tide_figure': 605})

    def test_tickets_mooring_line(self):
        self.assertEqual(tickets.mooring_line('1h30m'), {'mooring_line': 5400})
        self.assertEqual(tickets.mooring_line('45s'), {'mooring_line': 45})
        self.assertEqual(tickets.mooring_line('2h'), {'mooring_line': 7200})
        self.assertEqual(tickets.mooring_line('1h1m1s'), {'mooring_line': 3661})
        with self.assertRaises(ValueError):
            tickets.mooring_line('')
        with self.assertRaises(ValueError):
            tickets.mooring_line('5x')
        self.assertEqual(tickets.mooring_line('10m5s'), {'mooring_line': 605})

    def test_moved(self):
        new = pathlib.Path('atlas/core_math.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'parse_duration' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('atlas/archive.py').read_text(encoding="utf-8")
        self.assertNotIn('parse_duration', names(text))
