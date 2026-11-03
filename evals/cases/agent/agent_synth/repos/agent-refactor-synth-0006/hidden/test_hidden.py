import unittest

import ast
import pathlib

from lantern import ledger
from lantern import rosters
from lantern import survey


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
        self.assertEqual(ledger.page_of([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(ledger.page_of([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(ledger.page_of([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(ledger.page_of([], 1, 5), [])
        with self.assertRaises(ValueError):
            ledger.page_of([1, 2], 0, 2)

    def test_rosters_tide_row(self):
        self.assertEqual(rosters.tide_row([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), {'tide_row': [1, 2, 3]})
        self.assertEqual(rosters.tide_row([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), {'tide_row': [10]})
        self.assertEqual(rosters.tide_row([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), {'tide_row': []})
        self.assertEqual(rosters.tide_row([], 1, 5), {'tide_row': []})
        with self.assertRaises(ValueError):
            rosters.tide_row([1, 2], 0, 2)

    def test_survey_tide_view(self):
        self.assertEqual(survey.tide_view([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), {'tide_view': [1, 2, 3]})
        self.assertEqual(survey.tide_view([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), {'tide_view': [10]})
        self.assertEqual(survey.tide_view([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), {'tide_view': []})
        self.assertEqual(survey.tide_view([], 1, 5), {'tide_view': []})
        with self.assertRaises(ValueError):
            survey.tide_view([1, 2], 0, 2)

    def test_old_name_gone(self):
        self.assertFalse(hasattr(ledger, 'paginate'))
        for f in [*pathlib.Path('lantern').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('paginate', names(f.read_text(encoding="utf-8")), f)
