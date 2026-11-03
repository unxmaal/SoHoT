import unittest

import ast
import pathlib

from depot import archive
from depot import catalog
from depot import timesheet


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
        self.assertEqual(archive.mean_by_weight([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(archive.mean_by_weight([10, 20], [1, 3]), 17.5)
        self.assertEqual(archive.mean_by_weight([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            archive.mean_by_weight([5, 5], [0, 0])
        self.assertEqual(archive.mean_by_weight([1, 2], [0.5, 1.5]), 1.75)

    def test_timesheet_keel_summary(self):
        self.assertEqual(timesheet.keel_summary([1, 2, 3], [1, 1, 1]), {'keel_summary': 2.0})
        self.assertEqual(timesheet.keel_summary([10, 20], [1, 3]), {'keel_summary': 17.5})
        self.assertEqual(timesheet.keel_summary([4], [2]), {'keel_summary': 4.0})
        with self.assertRaises(ValueError):
            timesheet.keel_summary([5, 5], [0, 0])
        self.assertEqual(timesheet.keel_summary([1, 2], [0.5, 1.5]), {'keel_summary': 1.75})

    def test_catalog_mast_total(self):
        self.assertEqual(catalog.mast_total([1, 2, 3], [1, 1, 1]), {'mast_total': 2.0})
        self.assertEqual(catalog.mast_total([10, 20], [1, 3]), {'mast_total': 17.5})
        self.assertEqual(catalog.mast_total([4], [2]), {'mast_total': 4.0})
        with self.assertRaises(ValueError):
            catalog.mast_total([5, 5], [0, 0])
        self.assertEqual(catalog.mast_total([1, 2], [0.5, 1.5]), {'mast_total': 1.75})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(archive, 'weighted_mean'))
        for f in [*pathlib.Path('depot').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('weighted_mean', names(f.read_text(encoding="utf-8")), f)
