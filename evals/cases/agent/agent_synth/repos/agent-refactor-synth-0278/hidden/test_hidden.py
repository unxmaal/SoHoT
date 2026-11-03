import unittest

import ast
import pathlib

from granary import fleet
from granary import payroll
from granary import routes
from granary import tickets
from granary import weather


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
        self.assertEqual(tickets.join_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(tickets.join_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(tickets.join_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(tickets.join_ranges([]), [])
        self.assertEqual(tickets.join_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_weather_harbor_total(self):
        self.assertEqual(weather.harbor_total([(1, 3), (3, 5)]), {'harbor_total': [(1, 5)]})
        self.assertEqual(weather.harbor_total([(5, 6), (1, 2)]), {'harbor_total': [(1, 2), (5, 6)]})
        self.assertEqual(weather.harbor_total([(1, 10), (2, 3)]), {'harbor_total': [(1, 10)]})
        self.assertEqual(weather.harbor_total([]), {'harbor_total': []})
        self.assertEqual(weather.harbor_total([(4, 8), (1, 5)]), {'harbor_total': [(1, 8)]})

    def test_fleet_crate_figure(self):
        self.assertEqual(fleet.crate_figure([(1, 3), (3, 5)]), {'crate_figure': [(1, 5)]})
        self.assertEqual(fleet.crate_figure([(5, 6), (1, 2)]), {'crate_figure': [(1, 2), (5, 6)]})
        self.assertEqual(fleet.crate_figure([(1, 10), (2, 3)]), {'crate_figure': [(1, 10)]})
        self.assertEqual(fleet.crate_figure([]), {'crate_figure': []})
        self.assertEqual(fleet.crate_figure([(4, 8), (1, 5)]), {'crate_figure': [(1, 8)]})

    def test_routes_hull_entry(self):
        self.assertEqual(routes.hull_entry([(1, 3), (3, 5)]), {'hull_entry': [(1, 5)]})
        self.assertEqual(routes.hull_entry([(5, 6), (1, 2)]), {'hull_entry': [(1, 2), (5, 6)]})
        self.assertEqual(routes.hull_entry([(1, 10), (2, 3)]), {'hull_entry': [(1, 10)]})
        self.assertEqual(routes.hull_entry([]), {'hull_entry': []})
        self.assertEqual(routes.hull_entry([(4, 8), (1, 5)]), {'hull_entry': [(1, 8)]})

    def test_payroll_anchor_summary(self):
        self.assertEqual(payroll.anchor_summary([(1, 3), (3, 5)]), {'anchor_summary': [(1, 5)]})
        self.assertEqual(payroll.anchor_summary([(5, 6), (1, 2)]), {'anchor_summary': [(1, 2), (5, 6)]})
        self.assertEqual(payroll.anchor_summary([(1, 10), (2, 3)]), {'anchor_summary': [(1, 10)]})
        self.assertEqual(payroll.anchor_summary([]), {'anchor_summary': []})
        self.assertEqual(payroll.anchor_summary([(4, 8), (1, 5)]), {'anchor_summary': [(1, 8)]})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(tickets, 'merge_ranges'))
        for f in [*pathlib.Path('granary').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('merge_ranges', names(f.read_text(encoding="utf-8")), f)
