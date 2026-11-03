import unittest

import ast
import pathlib

from quarry import catalog
from quarry import ledger
from quarry import rosters


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
        self.assertEqual(ledger.money(0), '$0.00')
        self.assertEqual(ledger.money(123456), '$1,234.56')
        self.assertEqual(ledger.money(-105), '-$1.05')
        self.assertEqual(ledger.money(5), '$0.05')
        self.assertEqual(ledger.money(100000000), '$1,000,000.00')

    def test_catalog_crate_summary(self):
        self.assertEqual(catalog.crate_summary(0), {'crate_summary': '$0.00'})
        self.assertEqual(catalog.crate_summary(123456), {'crate_summary': '$1,234.56'})
        self.assertEqual(catalog.crate_summary(-105), {'crate_summary': '-$1.05'})
        self.assertEqual(catalog.crate_summary(5), {'crate_summary': '$0.05'})
        self.assertEqual(catalog.crate_summary(100000000), {'crate_summary': '$1,000,000.00'})

    def test_rosters_quay_view(self):
        self.assertEqual(rosters.quay_view(0), {'quay_view': '$0.00'})
        self.assertEqual(rosters.quay_view(123456), {'quay_view': '$1,234.56'})
        self.assertEqual(rosters.quay_view(-105), {'quay_view': '-$1.05'})
        self.assertEqual(rosters.quay_view(5), {'quay_view': '$0.05'})
        self.assertEqual(rosters.quay_view(100000000), {'quay_view': '$1,000,000.00'})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(ledger, 'format_cents'))
        for f in [*pathlib.Path('quarry').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('format_cents', names(f.read_text(encoding="utf-8")), f)
