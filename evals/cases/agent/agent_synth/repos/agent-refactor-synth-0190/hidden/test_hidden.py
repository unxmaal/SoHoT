import unittest

import ast
import pathlib

from foundry import catalog
from foundry import orders
from foundry import survey
from foundry import timesheet


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
        self.assertEqual(timesheet.encode_runs('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(timesheet.encode_runs(''), [])
        self.assertEqual(timesheet.encode_runs('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(timesheet.encode_runs('zz'), [('z', 2)])

    def test_catalog_rope_figure(self):
        self.assertEqual(catalog.rope_figure('aaab'), {'rope_figure': [('a', 3), ('b', 1)]})
        self.assertEqual(catalog.rope_figure(''), {'rope_figure': []})
        self.assertEqual(catalog.rope_figure('abc'), {'rope_figure': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(catalog.rope_figure('zz'), {'rope_figure': [('z', 2)]})

    def test_orders_harbor_row(self):
        self.assertEqual(orders.harbor_row('aaab'), {'harbor_row': [('a', 3), ('b', 1)]})
        self.assertEqual(orders.harbor_row(''), {'harbor_row': []})
        self.assertEqual(orders.harbor_row('abc'), {'harbor_row': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(orders.harbor_row('zz'), {'harbor_row': [('z', 2)]})

    def test_survey_cargo_row(self):
        self.assertEqual(survey.cargo_row('aaab'), {'cargo_row': [('a', 3), ('b', 1)]})
        self.assertEqual(survey.cargo_row(''), {'cargo_row': []})
        self.assertEqual(survey.cargo_row('abc'), {'cargo_row': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(survey.cargo_row('zz'), {'cargo_row': [('z', 2)]})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(timesheet, 'rle'))
        for f in [*pathlib.Path('foundry').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('rle', names(f.read_text(encoding="utf-8")), f)
