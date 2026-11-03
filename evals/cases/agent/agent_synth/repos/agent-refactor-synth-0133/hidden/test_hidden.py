import unittest

import ast
import pathlib

from depot import budget
from depot import routes
from depot import textual
from depot import timesheet


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
        self.assertEqual(textual.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(textual.running_total([]), [])
        self.assertEqual(textual.running_total([5]), [5])
        self.assertEqual(textual.running_total([2, -2, 2]), [2, 0, 2])

    def test_routes_tide_figure(self):
        self.assertEqual(routes.tide_figure([1, 2, 3]), {'tide_figure': [1, 3, 6]})
        self.assertEqual(routes.tide_figure([]), {'tide_figure': []})
        self.assertEqual(routes.tide_figure([5]), {'tide_figure': [5]})
        self.assertEqual(routes.tide_figure([2, -2, 2]), {'tide_figure': [2, 0, 2]})

    def test_timesheet_keel_figure(self):
        self.assertEqual(timesheet.keel_figure([1, 2, 3]), {'keel_figure': [1, 3, 6]})
        self.assertEqual(timesheet.keel_figure([]), {'keel_figure': []})
        self.assertEqual(timesheet.keel_figure([5]), {'keel_figure': [5]})
        self.assertEqual(timesheet.keel_figure([2, -2, 2]), {'keel_figure': [2, 0, 2]})

    def test_moved(self):
        new = pathlib.Path('depot/textual.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'running_total' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('depot/budget.py').read_text(encoding="utf-8")
        self.assertNotIn('running_total', names(text))
