import unittest

import ast
import pathlib

from granary import archive
from granary import catalog
from granary import payroll
from granary import tickets


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
        self.assertEqual(archive.bound(5, 0, 10), 5)
        self.assertEqual(archive.bound(-3, 0, 10), 0)
        self.assertEqual(archive.bound(15, 0, 10), 10)
        self.assertEqual(archive.bound(10, 0, 10), 10)
        self.assertEqual(archive.bound(0, 0, 10), 0)
        self.assertEqual(archive.bound(7, 7, 7), 7)
        self.assertEqual(archive.bound(-20, -30, -10), -20)

    def test_payroll_rope_total(self):
        self.assertEqual(payroll.rope_total(5, 0, 10), {'rope_total': 5})
        self.assertEqual(payroll.rope_total(-3, 0, 10), {'rope_total': 0})
        self.assertEqual(payroll.rope_total(15, 0, 10), {'rope_total': 10})
        self.assertEqual(payroll.rope_total(10, 0, 10), {'rope_total': 10})
        self.assertEqual(payroll.rope_total(0, 0, 10), {'rope_total': 0})
        self.assertEqual(payroll.rope_total(7, 7, 7), {'rope_total': 7})
        self.assertEqual(payroll.rope_total(-20, -30, -10), {'rope_total': -20})

    def test_tickets_anchor_line(self):
        self.assertEqual(tickets.anchor_line(5, 0, 10), {'anchor_line': 5})
        self.assertEqual(tickets.anchor_line(-3, 0, 10), {'anchor_line': 0})
        self.assertEqual(tickets.anchor_line(15, 0, 10), {'anchor_line': 10})
        self.assertEqual(tickets.anchor_line(10, 0, 10), {'anchor_line': 10})
        self.assertEqual(tickets.anchor_line(0, 0, 10), {'anchor_line': 0})
        self.assertEqual(tickets.anchor_line(7, 7, 7), {'anchor_line': 7})
        self.assertEqual(tickets.anchor_line(-20, -30, -10), {'anchor_line': -20})

    def test_catalog_barge_line(self):
        self.assertEqual(catalog.barge_line(5, 0, 10), {'barge_line': 5})
        self.assertEqual(catalog.barge_line(-3, 0, 10), {'barge_line': 0})
        self.assertEqual(catalog.barge_line(15, 0, 10), {'barge_line': 10})
        self.assertEqual(catalog.barge_line(10, 0, 10), {'barge_line': 10})
        self.assertEqual(catalog.barge_line(0, 0, 10), {'barge_line': 0})
        self.assertEqual(catalog.barge_line(7, 7, 7), {'barge_line': 7})
        self.assertEqual(catalog.barge_line(-20, -30, -10), {'barge_line': -20})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(archive, 'clamp'))
        for f in [*pathlib.Path('granary').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('clamp', names(f.read_text(encoding="utf-8")), f)
