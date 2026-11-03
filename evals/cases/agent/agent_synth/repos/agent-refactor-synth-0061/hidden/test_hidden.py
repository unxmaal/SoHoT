import unittest

import ast
import pathlib

from compass import archive
from compass import core_math
from compass import routes
from compass import shipping
from compass import tickets


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
        self.assertEqual(core_math.clamp(5, 0, 10), 5)
        self.assertEqual(core_math.clamp(-3, 0, 10), 0)
        self.assertEqual(core_math.clamp(15, 0, 10), 10)
        self.assertEqual(core_math.clamp(10, 0, 10), 10)
        self.assertEqual(core_math.clamp(0, 0, 10), 0)
        self.assertEqual(core_math.clamp(7, 7, 7), 7)
        self.assertEqual(core_math.clamp(-20, -30, -10), -20)

    def test_routes_barge_check(self):
        self.assertEqual(routes.barge_check(5, 0, 10), {'barge_check': 5})
        self.assertEqual(routes.barge_check(-3, 0, 10), {'barge_check': 0})
        self.assertEqual(routes.barge_check(15, 0, 10), {'barge_check': 10})
        self.assertEqual(routes.barge_check(10, 0, 10), {'barge_check': 10})
        self.assertEqual(routes.barge_check(0, 0, 10), {'barge_check': 0})
        self.assertEqual(routes.barge_check(7, 7, 7), {'barge_check': 7})
        self.assertEqual(routes.barge_check(-20, -30, -10), {'barge_check': -20})

    def test_shipping_anchor_summary(self):
        self.assertEqual(shipping.anchor_summary(5, 0, 10), {'anchor_summary': 5})
        self.assertEqual(shipping.anchor_summary(-3, 0, 10), {'anchor_summary': 0})
        self.assertEqual(shipping.anchor_summary(15, 0, 10), {'anchor_summary': 10})
        self.assertEqual(shipping.anchor_summary(10, 0, 10), {'anchor_summary': 10})
        self.assertEqual(shipping.anchor_summary(0, 0, 10), {'anchor_summary': 0})
        self.assertEqual(shipping.anchor_summary(7, 7, 7), {'anchor_summary': 7})
        self.assertEqual(shipping.anchor_summary(-20, -30, -10), {'anchor_summary': -20})

    def test_archive_lantern_view(self):
        self.assertEqual(archive.lantern_view(5, 0, 10), {'lantern_view': 5})
        self.assertEqual(archive.lantern_view(-3, 0, 10), {'lantern_view': 0})
        self.assertEqual(archive.lantern_view(15, 0, 10), {'lantern_view': 10})
        self.assertEqual(archive.lantern_view(10, 0, 10), {'lantern_view': 10})
        self.assertEqual(archive.lantern_view(0, 0, 10), {'lantern_view': 0})
        self.assertEqual(archive.lantern_view(7, 7, 7), {'lantern_view': 7})
        self.assertEqual(archive.lantern_view(-20, -30, -10), {'lantern_view': -20})

    def test_moved(self):
        new = pathlib.Path('compass/core_math.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'clamp' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('compass/tickets.py').read_text(encoding="utf-8")
        self.assertNotIn('clamp', names(text))
