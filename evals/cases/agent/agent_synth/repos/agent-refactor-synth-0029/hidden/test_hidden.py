import unittest

import ast
import pathlib

from granary import archive
from granary import catalog
from granary import pricing
from granary import shared
from granary import survey
from granary import timesheet


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
        self.assertEqual(shared.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(shared.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(shared.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(shared.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(shared.bucket(7, []), 0)

    def test_catalog_quay_view(self):
        self.assertEqual(catalog.quay_view(5, [0, 5, 10]), {'quay_view': 2})
        self.assertEqual(catalog.quay_view(-1, [0, 5, 10]), {'quay_view': 0})
        self.assertEqual(catalog.quay_view(12, [0, 5, 10]), {'quay_view': 3})
        self.assertEqual(catalog.quay_view(0, [0, 5, 10]), {'quay_view': 1})
        self.assertEqual(catalog.quay_view(7, []), {'quay_view': 0})

    def test_survey_mast_total(self):
        self.assertEqual(survey.mast_total(5, [0, 5, 10]), {'mast_total': 2})
        self.assertEqual(survey.mast_total(-1, [0, 5, 10]), {'mast_total': 0})
        self.assertEqual(survey.mast_total(12, [0, 5, 10]), {'mast_total': 3})
        self.assertEqual(survey.mast_total(0, [0, 5, 10]), {'mast_total': 1})
        self.assertEqual(survey.mast_total(7, []), {'mast_total': 0})

    def test_archive_berth_line(self):
        self.assertEqual(archive.berth_line(5, [0, 5, 10]), {'berth_line': 2})
        self.assertEqual(archive.berth_line(-1, [0, 5, 10]), {'berth_line': 0})
        self.assertEqual(archive.berth_line(12, [0, 5, 10]), {'berth_line': 3})
        self.assertEqual(archive.berth_line(0, [0, 5, 10]), {'berth_line': 1})
        self.assertEqual(archive.berth_line(7, []), {'berth_line': 0})

    def test_timesheet_sail_summary(self):
        self.assertEqual(timesheet.sail_summary(5, [0, 5, 10]), {'sail_summary': 2})
        self.assertEqual(timesheet.sail_summary(-1, [0, 5, 10]), {'sail_summary': 0})
        self.assertEqual(timesheet.sail_summary(12, [0, 5, 10]), {'sail_summary': 3})
        self.assertEqual(timesheet.sail_summary(0, [0, 5, 10]), {'sail_summary': 1})
        self.assertEqual(timesheet.sail_summary(7, []), {'sail_summary': 0})

    def test_moved(self):
        new = pathlib.Path('granary/shared.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'bucket' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('granary/pricing.py').read_text(encoding="utf-8")
        self.assertNotIn('bucket', names(text))
