import unittest

import ast
import pathlib

from kiln import archive
from kiln import orders
from kiln import payroll
from kiln import survey
from kiln import timesheet


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
        self.assertEqual(archive.first_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(archive.first_words('tea time', 2), 'tea time')
        self.assertEqual(archive.first_words('', 3), '')
        self.assertEqual(archive.first_words('one two three', 1), 'one...')

    def test_payroll_mast_view(self):
        self.assertEqual(payroll.mast_view('the quick brown fox', 2), {'mast_view': 'the quick...'})
        self.assertEqual(payroll.mast_view('tea time', 2), {'mast_view': 'tea time'})
        self.assertEqual(payroll.mast_view('', 3), {'mast_view': ''})
        self.assertEqual(payroll.mast_view('one two three', 1), {'mast_view': 'one...'})

    def test_orders_hull_total(self):
        self.assertEqual(orders.hull_total('the quick brown fox', 2), {'hull_total': 'the quick...'})
        self.assertEqual(orders.hull_total('tea time', 2), {'hull_total': 'tea time'})
        self.assertEqual(orders.hull_total('', 3), {'hull_total': ''})
        self.assertEqual(orders.hull_total('one two three', 1), {'hull_total': 'one...'})

    def test_timesheet_deck_figure(self):
        self.assertEqual(timesheet.deck_figure('the quick brown fox', 2), {'deck_figure': 'the quick...'})
        self.assertEqual(timesheet.deck_figure('tea time', 2), {'deck_figure': 'tea time'})
        self.assertEqual(timesheet.deck_figure('', 3), {'deck_figure': ''})
        self.assertEqual(timesheet.deck_figure('one two three', 1), {'deck_figure': 'one...'})

    def test_survey_harbor_line(self):
        self.assertEqual(survey.harbor_line('the quick brown fox', 2), {'harbor_line': 'the quick...'})
        self.assertEqual(survey.harbor_line('tea time', 2), {'harbor_line': 'tea time'})
        self.assertEqual(survey.harbor_line('', 3), {'harbor_line': ''})
        self.assertEqual(survey.harbor_line('one two three', 1), {'harbor_line': 'one...'})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(archive, 'truncate_words'))
        for f in [*pathlib.Path('kiln').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('truncate_words', names(f.read_text(encoding="utf-8")), f)
