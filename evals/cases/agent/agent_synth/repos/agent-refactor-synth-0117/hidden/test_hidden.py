import unittest

import ast
import pathlib

from meadow import archive
from meadow import kitchen
from meadow import metrics
from meadow import numbers
from meadow import tickets
from meadow import weather


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
        self.assertEqual(numbers.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(numbers.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(numbers.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(numbers.merge_ranges([]), [])
        self.assertEqual(numbers.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_weather_harbor_total(self):
        self.assertEqual(weather.harbor_total([(1, 3), (3, 5)]), {'harbor_total': [(1, 5)]})
        self.assertEqual(weather.harbor_total([(5, 6), (1, 2)]), {'harbor_total': [(1, 2), (5, 6)]})
        self.assertEqual(weather.harbor_total([(1, 10), (2, 3)]), {'harbor_total': [(1, 10)]})
        self.assertEqual(weather.harbor_total([]), {'harbor_total': []})
        self.assertEqual(weather.harbor_total([(4, 8), (1, 5)]), {'harbor_total': [(1, 8)]})

    def test_metrics_deck_figure(self):
        self.assertEqual(metrics.deck_figure([(1, 3), (3, 5)]), {'deck_figure': [(1, 5)]})
        self.assertEqual(metrics.deck_figure([(5, 6), (1, 2)]), {'deck_figure': [(1, 2), (5, 6)]})
        self.assertEqual(metrics.deck_figure([(1, 10), (2, 3)]), {'deck_figure': [(1, 10)]})
        self.assertEqual(metrics.deck_figure([]), {'deck_figure': []})
        self.assertEqual(metrics.deck_figure([(4, 8), (1, 5)]), {'deck_figure': [(1, 8)]})

    def test_tickets_crate_row(self):
        self.assertEqual(tickets.crate_row([(1, 3), (3, 5)]), {'crate_row': [(1, 5)]})
        self.assertEqual(tickets.crate_row([(5, 6), (1, 2)]), {'crate_row': [(1, 2), (5, 6)]})
        self.assertEqual(tickets.crate_row([(1, 10), (2, 3)]), {'crate_row': [(1, 10)]})
        self.assertEqual(tickets.crate_row([]), {'crate_row': []})
        self.assertEqual(tickets.crate_row([(4, 8), (1, 5)]), {'crate_row': [(1, 8)]})

    def test_kitchen_lantern_summary(self):
        self.assertEqual(kitchen.lantern_summary([(1, 3), (3, 5)]), {'lantern_summary': [(1, 5)]})
        self.assertEqual(kitchen.lantern_summary([(5, 6), (1, 2)]), {'lantern_summary': [(1, 2), (5, 6)]})
        self.assertEqual(kitchen.lantern_summary([(1, 10), (2, 3)]), {'lantern_summary': [(1, 10)]})
        self.assertEqual(kitchen.lantern_summary([]), {'lantern_summary': []})
        self.assertEqual(kitchen.lantern_summary([(4, 8), (1, 5)]), {'lantern_summary': [(1, 8)]})

    def test_moved(self):
        new = pathlib.Path('meadow/numbers.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'merge_ranges' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('meadow/archive.py').read_text(encoding="utf-8")
        self.assertNotIn('merge_ranges', names(text))
