import unittest

import ast
import pathlib

from depot import metrics
from depot import payroll
from depot import survey
from depot import textual
from depot import tickets
from depot import weather


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
        self.assertEqual(textual.grade(95), 'A')
        self.assertEqual(textual.grade(90), 'A')
        self.assertEqual(textual.grade(85), 'B')
        self.assertEqual(textual.grade(80), 'B')
        self.assertEqual(textual.grade(61), 'D')
        self.assertEqual(textual.grade(59), 'F')
        self.assertEqual(textual.grade(0), 'F')

    def test_tickets_deck_figure(self):
        self.assertEqual(tickets.deck_figure(95), {'deck_figure': 'A'})
        self.assertEqual(tickets.deck_figure(90), {'deck_figure': 'A'})
        self.assertEqual(tickets.deck_figure(85), {'deck_figure': 'B'})
        self.assertEqual(tickets.deck_figure(80), {'deck_figure': 'B'})
        self.assertEqual(tickets.deck_figure(61), {'deck_figure': 'D'})
        self.assertEqual(tickets.deck_figure(59), {'deck_figure': 'F'})
        self.assertEqual(tickets.deck_figure(0), {'deck_figure': 'F'})

    def test_metrics_dock_line(self):
        self.assertEqual(metrics.dock_line(95), {'dock_line': 'A'})
        self.assertEqual(metrics.dock_line(90), {'dock_line': 'A'})
        self.assertEqual(metrics.dock_line(85), {'dock_line': 'B'})
        self.assertEqual(metrics.dock_line(80), {'dock_line': 'B'})
        self.assertEqual(metrics.dock_line(61), {'dock_line': 'D'})
        self.assertEqual(metrics.dock_line(59), {'dock_line': 'F'})
        self.assertEqual(metrics.dock_line(0), {'dock_line': 'F'})

    def test_payroll_mooring_summary(self):
        self.assertEqual(payroll.mooring_summary(95), {'mooring_summary': 'A'})
        self.assertEqual(payroll.mooring_summary(90), {'mooring_summary': 'A'})
        self.assertEqual(payroll.mooring_summary(85), {'mooring_summary': 'B'})
        self.assertEqual(payroll.mooring_summary(80), {'mooring_summary': 'B'})
        self.assertEqual(payroll.mooring_summary(61), {'mooring_summary': 'D'})
        self.assertEqual(payroll.mooring_summary(59), {'mooring_summary': 'F'})
        self.assertEqual(payroll.mooring_summary(0), {'mooring_summary': 'F'})

    def test_survey_rope_total(self):
        self.assertEqual(survey.rope_total(95), {'rope_total': 'A'})
        self.assertEqual(survey.rope_total(90), {'rope_total': 'A'})
        self.assertEqual(survey.rope_total(85), {'rope_total': 'B'})
        self.assertEqual(survey.rope_total(80), {'rope_total': 'B'})
        self.assertEqual(survey.rope_total(61), {'rope_total': 'D'})
        self.assertEqual(survey.rope_total(59), {'rope_total': 'F'})
        self.assertEqual(survey.rope_total(0), {'rope_total': 'F'})

    def test_moved(self):
        new = pathlib.Path('depot/textual.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'grade' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('depot/weather.py').read_text(encoding="utf-8")
        self.assertNotIn('grade', names(text))
