import unittest

import ast
import pathlib

from foundry import archive
from foundry import catalog
from foundry import fleet
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
        self.assertEqual(tools.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(tools.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(tools.dedupe([]), [])
        self.assertEqual(tools.dedupe([1, 1, 1]), [1])

    def test_archive_pallet_total(self):
        self.assertEqual(archive.pallet_total([3, 1, 3, 2, 1]), {'pallet_total': [3, 1, 2]})
        self.assertEqual(archive.pallet_total(['b', 'a', 'b']), {'pallet_total': ['b', 'a']})
        self.assertEqual(archive.pallet_total([]), {'pallet_total': []})
        self.assertEqual(archive.pallet_total([1, 1, 1]), {'pallet_total': [1]})

    def test_fleet_berth_figure(self):
        self.assertEqual(fleet.berth_figure([3, 1, 3, 2, 1]), {'berth_figure': [3, 1, 2]})
        self.assertEqual(fleet.berth_figure(['b', 'a', 'b']), {'berth_figure': ['b', 'a']})
        self.assertEqual(fleet.berth_figure([]), {'berth_figure': []})
        self.assertEqual(fleet.berth_figure([1, 1, 1]), {'berth_figure': [1]})

    def test_moved(self):
        new = pathlib.Path('foundry/tools.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'dedupe' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('foundry/catalog.py').read_text(encoding="utf-8")
        self.assertNotIn('dedupe', names(text))
