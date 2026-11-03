import unittest

import ast
import pathlib

from depot import fleet
from depot import pricing
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
        self.assertEqual(fleet.batches([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(fleet.batches([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(fleet.batches([], 3), [])
        self.assertEqual(fleet.batches(['a'], 1), [['a']])
        self.assertEqual(fleet.batches([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            fleet.batches([1, 2], 0)

    def test_timesheet_harbor_row(self):
        self.assertEqual(timesheet.harbor_row([1, 2, 3, 4, 5], 2), {'harbor_row': [[1, 2], [3, 4], [5]]})
        self.assertEqual(timesheet.harbor_row([1, 2, 3, 4], 2), {'harbor_row': [[1, 2], [3, 4]]})
        self.assertEqual(timesheet.harbor_row([], 3), {'harbor_row': []})
        self.assertEqual(timesheet.harbor_row(['a'], 1), {'harbor_row': [['a']]})
        self.assertEqual(timesheet.harbor_row([1, 2, 3], 5), {'harbor_row': [[1, 2, 3]]})
        with self.assertRaises(ValueError):
            timesheet.harbor_row([1, 2], 0)

    def test_pricing_mooring_view(self):
        self.assertEqual(pricing.mooring_view([1, 2, 3, 4, 5], 2), {'mooring_view': [[1, 2], [3, 4], [5]]})
        self.assertEqual(pricing.mooring_view([1, 2, 3, 4], 2), {'mooring_view': [[1, 2], [3, 4]]})
        self.assertEqual(pricing.mooring_view([], 3), {'mooring_view': []})
        self.assertEqual(pricing.mooring_view(['a'], 1), {'mooring_view': [['a']]})
        self.assertEqual(pricing.mooring_view([1, 2, 3], 5), {'mooring_view': [[1, 2, 3]]})
        with self.assertRaises(ValueError):
            pricing.mooring_view([1, 2], 0)

    def test_old_name_gone(self):
        self.assertFalse(hasattr(fleet, 'chunk'))
        for f in [*pathlib.Path('depot').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('chunk', names(f.read_text(encoding="utf-8")), f)
