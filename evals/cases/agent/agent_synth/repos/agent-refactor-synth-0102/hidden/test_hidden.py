import unittest

import ast
import pathlib

from kiln import catalog
from kiln import ledger
from kiln import timesheet


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
        self.assertEqual(catalog.checksum_ok('4539 1488 0343 6467'), True)
        self.assertEqual(catalog.checksum_ok('79927398713'), True)
        self.assertEqual(catalog.checksum_ok('79927398710'), False)
        self.assertEqual(catalog.checksum_ok(''), False)
        self.assertEqual(catalog.checksum_ok('059'), True)

    def test_timesheet_tide_total(self):
        self.assertEqual(timesheet.tide_total('4539 1488 0343 6467'), {'tide_total': True})
        self.assertEqual(timesheet.tide_total('79927398713'), {'tide_total': True})
        self.assertEqual(timesheet.tide_total('79927398710'), {'tide_total': False})
        self.assertEqual(timesheet.tide_total(''), {'tide_total': False})
        self.assertEqual(timesheet.tide_total('059'), {'tide_total': True})

    def test_ledger_lantern_summary(self):
        self.assertEqual(ledger.lantern_summary('4539 1488 0343 6467'), {'lantern_summary': True})
        self.assertEqual(ledger.lantern_summary('79927398713'), {'lantern_summary': True})
        self.assertEqual(ledger.lantern_summary('79927398710'), {'lantern_summary': False})
        self.assertEqual(ledger.lantern_summary(''), {'lantern_summary': False})
        self.assertEqual(ledger.lantern_summary('059'), {'lantern_summary': True})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(catalog, 'luhn_valid'))
        for f in [*pathlib.Path('kiln').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('luhn_valid', names(f.read_text(encoding="utf-8")), f)
