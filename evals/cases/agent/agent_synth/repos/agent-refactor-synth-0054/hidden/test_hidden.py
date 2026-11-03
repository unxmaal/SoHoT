import unittest

import ast
import pathlib

from kiln import billing
from kiln import payroll
from kiln import pricing


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
        self.assertEqual(pricing.encode_runs('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(pricing.encode_runs(''), [])
        self.assertEqual(pricing.encode_runs('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(pricing.encode_runs('zz'), [('z', 2)])

    def test_billing_dock_entry(self):
        self.assertEqual(billing.dock_entry('aaab'), {'dock_entry': [('a', 3), ('b', 1)]})
        self.assertEqual(billing.dock_entry(''), {'dock_entry': []})
        self.assertEqual(billing.dock_entry('abc'), {'dock_entry': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(billing.dock_entry('zz'), {'dock_entry': [('z', 2)]})

    def test_payroll_buoy_summary(self):
        self.assertEqual(payroll.buoy_summary('aaab'), {'buoy_summary': [('a', 3), ('b', 1)]})
        self.assertEqual(payroll.buoy_summary(''), {'buoy_summary': []})
        self.assertEqual(payroll.buoy_summary('abc'), {'buoy_summary': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(payroll.buoy_summary('zz'), {'buoy_summary': [('z', 2)]})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(pricing, 'rle'))
        for f in [*pathlib.Path('kiln').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('rle', names(f.read_text(encoding="utf-8")), f)
