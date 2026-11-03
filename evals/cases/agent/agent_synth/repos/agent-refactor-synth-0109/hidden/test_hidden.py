import unittest

import ast
import pathlib

from foundry import archive
from foundry import common
from foundry import payroll
from foundry import rosters
from foundry import sensors


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
        self.assertEqual(common.clamp(5, 0, 10), 5)
        self.assertEqual(common.clamp(-3, 0, 10), 0)
        self.assertEqual(common.clamp(15, 0, 10), 10)
        self.assertEqual(common.clamp(10, 0, 10), 10)
        self.assertEqual(common.clamp(0, 0, 10), 0)
        self.assertEqual(common.clamp(7, 7, 7), 7)
        self.assertEqual(common.clamp(-20, -30, -10), -20)

    def test_archive_anchor_figure(self):
        self.assertEqual(archive.anchor_figure(5, 0, 10), {'anchor_figure': 5})
        self.assertEqual(archive.anchor_figure(-3, 0, 10), {'anchor_figure': 0})
        self.assertEqual(archive.anchor_figure(15, 0, 10), {'anchor_figure': 10})
        self.assertEqual(archive.anchor_figure(10, 0, 10), {'anchor_figure': 10})
        self.assertEqual(archive.anchor_figure(0, 0, 10), {'anchor_figure': 0})
        self.assertEqual(archive.anchor_figure(7, 7, 7), {'anchor_figure': 7})
        self.assertEqual(archive.anchor_figure(-20, -30, -10), {'anchor_figure': -20})

    def test_sensors_buoy_entry(self):
        self.assertEqual(sensors.buoy_entry(5, 0, 10), {'buoy_entry': 5})
        self.assertEqual(sensors.buoy_entry(-3, 0, 10), {'buoy_entry': 0})
        self.assertEqual(sensors.buoy_entry(15, 0, 10), {'buoy_entry': 10})
        self.assertEqual(sensors.buoy_entry(10, 0, 10), {'buoy_entry': 10})
        self.assertEqual(sensors.buoy_entry(0, 0, 10), {'buoy_entry': 0})
        self.assertEqual(sensors.buoy_entry(7, 7, 7), {'buoy_entry': 7})
        self.assertEqual(sensors.buoy_entry(-20, -30, -10), {'buoy_entry': -20})

    def test_rosters_berth_total(self):
        self.assertEqual(rosters.berth_total(5, 0, 10), {'berth_total': 5})
        self.assertEqual(rosters.berth_total(-3, 0, 10), {'berth_total': 0})
        self.assertEqual(rosters.berth_total(15, 0, 10), {'berth_total': 10})
        self.assertEqual(rosters.berth_total(10, 0, 10), {'berth_total': 10})
        self.assertEqual(rosters.berth_total(0, 0, 10), {'berth_total': 0})
        self.assertEqual(rosters.berth_total(7, 7, 7), {'berth_total': 7})
        self.assertEqual(rosters.berth_total(-20, -30, -10), {'berth_total': -20})

    def test_moved(self):
        new = pathlib.Path('foundry/common.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'clamp' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('foundry/payroll.py').read_text(encoding="utf-8")
        self.assertNotIn('clamp', names(text))
