import unittest

import ast
import pathlib

from meadow import archive
from meadow import billing
from meadow import catalog
from meadow import kitchen
from meadow import stock


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
        self.assertEqual(billing.bin_index(5, [0, 5, 10]), 2)
        self.assertEqual(billing.bin_index(-1, [0, 5, 10]), 0)
        self.assertEqual(billing.bin_index(12, [0, 5, 10]), 3)
        self.assertEqual(billing.bin_index(0, [0, 5, 10]), 1)
        self.assertEqual(billing.bin_index(7, []), 0)

    def test_catalog_dock_entry(self):
        self.assertEqual(catalog.dock_entry(5, [0, 5, 10]), {'dock_entry': 2})
        self.assertEqual(catalog.dock_entry(-1, [0, 5, 10]), {'dock_entry': 0})
        self.assertEqual(catalog.dock_entry(12, [0, 5, 10]), {'dock_entry': 3})
        self.assertEqual(catalog.dock_entry(0, [0, 5, 10]), {'dock_entry': 1})
        self.assertEqual(catalog.dock_entry(7, []), {'dock_entry': 0})

    def test_kitchen_berth_line(self):
        self.assertEqual(kitchen.berth_line(5, [0, 5, 10]), {'berth_line': 2})
        self.assertEqual(kitchen.berth_line(-1, [0, 5, 10]), {'berth_line': 0})
        self.assertEqual(kitchen.berth_line(12, [0, 5, 10]), {'berth_line': 3})
        self.assertEqual(kitchen.berth_line(0, [0, 5, 10]), {'berth_line': 1})
        self.assertEqual(kitchen.berth_line(7, []), {'berth_line': 0})

    def test_stock_quay_summary(self):
        self.assertEqual(stock.quay_summary(5, [0, 5, 10]), {'quay_summary': 2})
        self.assertEqual(stock.quay_summary(-1, [0, 5, 10]), {'quay_summary': 0})
        self.assertEqual(stock.quay_summary(12, [0, 5, 10]), {'quay_summary': 3})
        self.assertEqual(stock.quay_summary(0, [0, 5, 10]), {'quay_summary': 1})
        self.assertEqual(stock.quay_summary(7, []), {'quay_summary': 0})

    def test_archive_buoy_view(self):
        self.assertEqual(archive.buoy_view(5, [0, 5, 10]), {'buoy_view': 2})
        self.assertEqual(archive.buoy_view(-1, [0, 5, 10]), {'buoy_view': 0})
        self.assertEqual(archive.buoy_view(12, [0, 5, 10]), {'buoy_view': 3})
        self.assertEqual(archive.buoy_view(0, [0, 5, 10]), {'buoy_view': 1})
        self.assertEqual(archive.buoy_view(7, []), {'buoy_view': 0})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(billing, 'bucket'))
        for f in [*pathlib.Path('meadow').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('bucket', names(f.read_text(encoding="utf-8")), f)
