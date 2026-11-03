import unittest

import ast
import pathlib

from kiln import archive
from kiln import common
from kiln import fleet
from kiln import kitchen
from kiln import sensors
from kiln import weather


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
        self.assertEqual(common.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(common.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(common.dedupe([]), [])
        self.assertEqual(common.dedupe([1, 1, 1]), [1])

    def test_sensors_anchor_line(self):
        self.assertEqual(sensors.anchor_line([3, 1, 3, 2, 1]), {'anchor_line': [3, 1, 2]})
        self.assertEqual(sensors.anchor_line(['b', 'a', 'b']), {'anchor_line': ['b', 'a']})
        self.assertEqual(sensors.anchor_line([]), {'anchor_line': []})
        self.assertEqual(sensors.anchor_line([1, 1, 1]), {'anchor_line': [1]})

    def test_kitchen_mooring_check(self):
        self.assertEqual(kitchen.mooring_check([3, 1, 3, 2, 1]), {'mooring_check': [3, 1, 2]})
        self.assertEqual(kitchen.mooring_check(['b', 'a', 'b']), {'mooring_check': ['b', 'a']})
        self.assertEqual(kitchen.mooring_check([]), {'mooring_check': []})
        self.assertEqual(kitchen.mooring_check([1, 1, 1]), {'mooring_check': [1]})

    def test_fleet_harbor_figure(self):
        self.assertEqual(fleet.harbor_figure([3, 1, 3, 2, 1]), {'harbor_figure': [3, 1, 2]})
        self.assertEqual(fleet.harbor_figure(['b', 'a', 'b']), {'harbor_figure': ['b', 'a']})
        self.assertEqual(fleet.harbor_figure([]), {'harbor_figure': []})
        self.assertEqual(fleet.harbor_figure([1, 1, 1]), {'harbor_figure': [1]})

    def test_archive_mooring_figure(self):
        self.assertEqual(archive.mooring_figure([3, 1, 3, 2, 1]), {'mooring_figure': [3, 1, 2]})
        self.assertEqual(archive.mooring_figure(['b', 'a', 'b']), {'mooring_figure': ['b', 'a']})
        self.assertEqual(archive.mooring_figure([]), {'mooring_figure': []})
        self.assertEqual(archive.mooring_figure([1, 1, 1]), {'mooring_figure': [1]})

    def test_moved(self):
        new = pathlib.Path('kiln/common.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'dedupe' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('kiln/weather.py').read_text(encoding="utf-8")
        self.assertNotIn('dedupe', names(text))
