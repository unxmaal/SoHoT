import unittest

import ast
import pathlib

from depot import archive
from depot import core_math
from depot import payroll
from depot import sensors


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
        self.assertEqual(core_math.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(core_math.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(core_math.dedupe([]), [])
        self.assertEqual(core_math.dedupe([1, 1, 1]), [1])

    def test_sensors_dock_line(self):
        self.assertEqual(sensors.dock_line([3, 1, 3, 2, 1]), {'dock_line': [3, 1, 2]})
        self.assertEqual(sensors.dock_line(['b', 'a', 'b']), {'dock_line': ['b', 'a']})
        self.assertEqual(sensors.dock_line([]), {'dock_line': []})
        self.assertEqual(sensors.dock_line([1, 1, 1]), {'dock_line': [1]})

    def test_archive_rope_summary(self):
        self.assertEqual(archive.rope_summary([3, 1, 3, 2, 1]), {'rope_summary': [3, 1, 2]})
        self.assertEqual(archive.rope_summary(['b', 'a', 'b']), {'rope_summary': ['b', 'a']})
        self.assertEqual(archive.rope_summary([]), {'rope_summary': []})
        self.assertEqual(archive.rope_summary([1, 1, 1]), {'rope_summary': [1]})

    def test_moved(self):
        new = pathlib.Path('depot/core_math.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'dedupe' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('depot/payroll.py').read_text(encoding="utf-8")
        self.assertNotIn('dedupe', names(text))
