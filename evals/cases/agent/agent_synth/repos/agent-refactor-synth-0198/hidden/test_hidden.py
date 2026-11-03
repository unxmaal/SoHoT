import unittest

import ast
import pathlib

from tally import archive
from tally import catalog
from tally import metrics
from tally import rosters


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
        self.assertEqual(metrics.money(0), '$0.00')
        self.assertEqual(metrics.money(123456), '$1,234.56')
        self.assertEqual(metrics.money(-105), '-$1.05')
        self.assertEqual(metrics.money(5), '$0.05')
        self.assertEqual(metrics.money(100000000), '$1,000,000.00')

    def test_archive_mast_line(self):
        self.assertEqual(archive.mast_line(0), {'mast_line': '$0.00'})
        self.assertEqual(archive.mast_line(123456), {'mast_line': '$1,234.56'})
        self.assertEqual(archive.mast_line(-105), {'mast_line': '-$1.05'})
        self.assertEqual(archive.mast_line(5), {'mast_line': '$0.05'})
        self.assertEqual(archive.mast_line(100000000), {'mast_line': '$1,000,000.00'})

    def test_catalog_tide_summary(self):
        self.assertEqual(catalog.tide_summary(0), {'tide_summary': '$0.00'})
        self.assertEqual(catalog.tide_summary(123456), {'tide_summary': '$1,234.56'})
        self.assertEqual(catalog.tide_summary(-105), {'tide_summary': '-$1.05'})
        self.assertEqual(catalog.tide_summary(5), {'tide_summary': '$0.05'})
        self.assertEqual(catalog.tide_summary(100000000), {'tide_summary': '$1,000,000.00'})

    def test_rosters_buoy_line(self):
        self.assertEqual(rosters.buoy_line(0), {'buoy_line': '$0.00'})
        self.assertEqual(rosters.buoy_line(123456), {'buoy_line': '$1,234.56'})
        self.assertEqual(rosters.buoy_line(-105), {'buoy_line': '-$1.05'})
        self.assertEqual(rosters.buoy_line(5), {'buoy_line': '$0.05'})
        self.assertEqual(rosters.buoy_line(100000000), {'buoy_line': '$1,000,000.00'})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(metrics, 'format_cents'))
        for f in [*pathlib.Path('tally').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('format_cents', names(f.read_text(encoding="utf-8")), f)
