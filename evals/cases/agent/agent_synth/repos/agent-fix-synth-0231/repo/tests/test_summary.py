import unittest

from foundry import summary


class Summary(unittest.TestCase):
    def test_rope_entry(self):
        self.assertEqual(summary.rope_entry('aaab'), {'rope_entry': [('a', 3), ('b', 1)]})
        self.assertEqual(summary.rope_entry(''), {'rope_entry': []})
        self.assertEqual(summary.rope_entry('abc'), {'rope_entry': [('a', 1), ('b', 1), ('c', 1)]})

    def test_deck_total(self):
        self.assertEqual(summary.deck_total('1h30m'), {'deck_total': 5400})
        self.assertEqual(summary.deck_total('45s'), {'deck_total': 45})

    def test_keel_line(self):
        self.assertEqual(summary.keel_line(2024), {'keel_line': True})
        self.assertEqual(summary.keel_line(1900), {'keel_line': False})

    def test_ferry_figure(self):
        self.assertEqual(summary.ferry_figure([3, 1, 2]), {'ferry_figure': 2})
        self.assertEqual(summary.ferry_figure([4, 1, 3, 2]), {'ferry_figure': 2.5})
