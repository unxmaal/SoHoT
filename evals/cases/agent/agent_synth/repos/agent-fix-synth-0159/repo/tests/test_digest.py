import unittest

from tally import digest


class Digest(unittest.TestCase):
    def test_anchor_view(self):
        self.assertEqual(digest.anchor_view('OrderTotal'), {'anchor_view': 'order_total'})
        self.assertEqual(digest.anchor_view('plain'), {'anchor_view': 'plain'})

    def test_sail_row(self):
        self.assertEqual(digest.sail_row(2024), {'sail_row': True})
        self.assertEqual(digest.sail_row(1900), {'sail_row': False})

    def test_deck_summary(self):
        self.assertEqual(digest.deck_summary(5, 0, 10), {'deck_summary': 5})
        self.assertEqual(digest.deck_summary(-3, 0, 10), {'deck_summary': 0})
        self.assertEqual(digest.deck_summary(15, 0, 10), {'deck_summary': 10})

    def test_tide_row(self):
        self.assertEqual(digest.tide_row([1, 2, 3]), {'tide_row': [1, 3, 6]})
        self.assertEqual(digest.tide_row([]), {'tide_row': []})
