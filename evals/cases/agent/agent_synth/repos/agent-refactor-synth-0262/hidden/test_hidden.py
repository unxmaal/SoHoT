import unittest

import ast
import pathlib

from depot import catalog
from depot import fleet
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
        self.assertEqual(fleet.coalesce([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(fleet.coalesce([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(fleet.coalesce([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(fleet.coalesce([]), [])
        self.assertEqual(fleet.coalesce([(4, 8), (1, 5)]), [(1, 8)])

    def test_sensors_barge_entry(self):
        self.assertEqual(sensors.barge_entry([(1, 3), (3, 5)]), {'barge_entry': [(1, 5)]})
        self.assertEqual(sensors.barge_entry([(5, 6), (1, 2)]), {'barge_entry': [(1, 2), (5, 6)]})
        self.assertEqual(sensors.barge_entry([(1, 10), (2, 3)]), {'barge_entry': [(1, 10)]})
        self.assertEqual(sensors.barge_entry([]), {'barge_entry': []})
        self.assertEqual(sensors.barge_entry([(4, 8), (1, 5)]), {'barge_entry': [(1, 8)]})

    def test_catalog_crate_total(self):
        self.assertEqual(catalog.crate_total([(1, 3), (3, 5)]), {'crate_total': [(1, 5)]})
        self.assertEqual(catalog.crate_total([(5, 6), (1, 2)]), {'crate_total': [(1, 2), (5, 6)]})
        self.assertEqual(catalog.crate_total([(1, 10), (2, 3)]), {'crate_total': [(1, 10)]})
        self.assertEqual(catalog.crate_total([]), {'crate_total': []})
        self.assertEqual(catalog.crate_total([(4, 8), (1, 5)]), {'crate_total': [(1, 8)]})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(fleet, 'merge_ranges'))
        for f in [*pathlib.Path('depot').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('merge_ranges', names(f.read_text(encoding="utf-8")), f)
