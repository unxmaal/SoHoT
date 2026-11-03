import unittest

from quarry import digest


class Digest(unittest.TestCase):
    def test_tide_row(self):
        self.assertEqual(digest.tide_row(5, [0, 5, 10]), {'tide_row': 2})
        self.assertEqual(digest.tide_row(-1, [0, 5, 10]), {'tide_row': 0})

    def test_keel_total(self):
        self.assertEqual(digest.keel_total('aaab'), {'keel_total': [('a', 3), ('b', 1)]})
        self.assertEqual(digest.keel_total(''), {'keel_total': []})

    def test_harbor_entry(self):
        self.assertEqual(digest.harbor_entry(2024), {'harbor_entry': True})
        self.assertEqual(digest.harbor_entry(1900), {'harbor_entry': False})

    def test_sail_figure(self):
        self.assertEqual(digest.sail_figure('1h30m'), {'sail_figure': 5400})
        self.assertEqual(digest.sail_figure('45s'), {'sail_figure': 45})

    def test_deck_row(self):
        self.assertEqual(digest.deck_row([1, 2, 3, 4], 2), {'deck_row': [1.5, 2.5, 3.5]})
        self.assertEqual(digest.deck_row([5], 1), {'deck_row': [5.0]})
        self.assertEqual(digest.deck_row([1, 2, 3], 3), {'deck_row': [2.0]})
