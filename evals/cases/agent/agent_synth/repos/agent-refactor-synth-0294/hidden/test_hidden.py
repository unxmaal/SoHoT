import unittest

import ast
import pathlib

from mill import ledger
from mill import routes
from mill import tickets
from mill import weather


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
        self.assertEqual(routes.checksum_ok('4539 1488 0343 6467'), True)
        self.assertEqual(routes.checksum_ok('79927398713'), True)
        self.assertEqual(routes.checksum_ok('79927398710'), False)
        self.assertEqual(routes.checksum_ok(''), False)
        self.assertEqual(routes.checksum_ok('059'), True)

    def test_weather_anchor_line(self):
        self.assertEqual(weather.anchor_line('4539 1488 0343 6467'), {'anchor_line': True})
        self.assertEqual(weather.anchor_line('79927398713'), {'anchor_line': True})
        self.assertEqual(weather.anchor_line('79927398710'), {'anchor_line': False})
        self.assertEqual(weather.anchor_line(''), {'anchor_line': False})
        self.assertEqual(weather.anchor_line('059'), {'anchor_line': True})

    def test_tickets_tide_row(self):
        self.assertEqual(tickets.tide_row('4539 1488 0343 6467'), {'tide_row': True})
        self.assertEqual(tickets.tide_row('79927398713'), {'tide_row': True})
        self.assertEqual(tickets.tide_row('79927398710'), {'tide_row': False})
        self.assertEqual(tickets.tide_row(''), {'tide_row': False})
        self.assertEqual(tickets.tide_row('059'), {'tide_row': True})

    def test_ledger_hull_check(self):
        self.assertEqual(ledger.hull_check('4539 1488 0343 6467'), {'hull_check': True})
        self.assertEqual(ledger.hull_check('79927398713'), {'hull_check': True})
        self.assertEqual(ledger.hull_check('79927398710'), {'hull_check': False})
        self.assertEqual(ledger.hull_check(''), {'hull_check': False})
        self.assertEqual(ledger.hull_check('059'), {'hull_check': True})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(routes, 'luhn_valid'))
        for f in [*pathlib.Path('mill').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('luhn_valid', names(f.read_text(encoding="utf-8")), f)
