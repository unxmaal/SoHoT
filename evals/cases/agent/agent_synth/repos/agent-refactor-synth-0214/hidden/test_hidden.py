import unittest

import ast
import pathlib

from kiln import catalog
from kiln import metrics
from kiln import payroll
from kiln import tickets


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
        self.assertEqual(catalog.has_feb_29(2024), True)
        self.assertEqual(catalog.has_feb_29(1900), False)
        self.assertEqual(catalog.has_feb_29(2000), True)
        self.assertEqual(catalog.has_feb_29(2023), False)
        self.assertEqual(catalog.has_feb_29(2400), True)
        self.assertEqual(catalog.has_feb_29(2100), False)

    def test_payroll_ferry_summary(self):
        self.assertEqual(payroll.ferry_summary(2024), {'ferry_summary': True})
        self.assertEqual(payroll.ferry_summary(1900), {'ferry_summary': False})
        self.assertEqual(payroll.ferry_summary(2000), {'ferry_summary': True})
        self.assertEqual(payroll.ferry_summary(2023), {'ferry_summary': False})
        self.assertEqual(payroll.ferry_summary(2400), {'ferry_summary': True})
        self.assertEqual(payroll.ferry_summary(2100), {'ferry_summary': False})

    def test_metrics_buoy_entry(self):
        self.assertEqual(metrics.buoy_entry(2024), {'buoy_entry': True})
        self.assertEqual(metrics.buoy_entry(1900), {'buoy_entry': False})
        self.assertEqual(metrics.buoy_entry(2000), {'buoy_entry': True})
        self.assertEqual(metrics.buoy_entry(2023), {'buoy_entry': False})
        self.assertEqual(metrics.buoy_entry(2400), {'buoy_entry': True})
        self.assertEqual(metrics.buoy_entry(2100), {'buoy_entry': False})

    def test_tickets_dock_figure(self):
        self.assertEqual(tickets.dock_figure(2024), {'dock_figure': True})
        self.assertEqual(tickets.dock_figure(1900), {'dock_figure': False})
        self.assertEqual(tickets.dock_figure(2000), {'dock_figure': True})
        self.assertEqual(tickets.dock_figure(2023), {'dock_figure': False})
        self.assertEqual(tickets.dock_figure(2400), {'dock_figure': True})
        self.assertEqual(tickets.dock_figure(2100), {'dock_figure': False})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(catalog, 'is_leap'))
        for f in [*pathlib.Path('kiln').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('is_leap', names(f.read_text(encoding="utf-8")), f)
