import unittest

from lantern import digest


class Digest(unittest.TestCase):
    def test_dock_line(self):
        self.assertEqual(digest.dock_line('aaab'), {'dock_line': [('a', 3), ('b', 1)]})
        self.assertEqual(digest.dock_line(''), {'dock_line': []})

    def test_lantern_figure(self):
        self.assertEqual(digest.lantern_figure([1, 2, 3], [1, 1, 1]), {'lantern_figure': 2.0})
        self.assertEqual(digest.lantern_figure([10, 20], [1, 3]), {'lantern_figure': 17.5})

    def test_keel_total(self):
        self.assertEqual(digest.keel_total([(1, 3), (3, 5)]), {'keel_total': [(1, 5)]})
        self.assertEqual(digest.keel_total([(5, 6), (1, 2)]), {'keel_total': [(1, 2), (5, 6)]})

    def test_ferry_row(self):
        self.assertEqual(digest.ferry_row(5, [0, 5, 10]), {'ferry_row': 2})
        self.assertEqual(digest.ferry_row(-1, [0, 5, 10]), {'ferry_row': 0})

    def test_deck_summary(self):
        self.assertEqual(digest.deck_summary(5, 0, 10), {'deck_summary': 5})
        self.assertEqual(digest.deck_summary(-3, 0, 10), {'deck_summary': 0})
        self.assertEqual(digest.deck_summary(15, 0, 10), {'deck_summary': 10})
