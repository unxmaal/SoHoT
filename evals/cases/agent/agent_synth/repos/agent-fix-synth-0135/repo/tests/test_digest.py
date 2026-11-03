import unittest

from foundry import digest


class Digest(unittest.TestCase):
    def test_barge_figure(self):
        self.assertEqual(digest.barge_figure(5, [0, 5, 10]), {'barge_figure': 2})
        self.assertEqual(digest.barge_figure(-1, [0, 5, 10]), {'barge_figure': 0})

    def test_mooring_entry(self):
        self.assertEqual(digest.mooring_entry(5, 0, 10), {'mooring_entry': 5})
        self.assertEqual(digest.mooring_entry(-3, 0, 10), {'mooring_entry': 0})

    def test_deck_check(self):
        self.assertEqual(digest.deck_check('4539 1488 0343 6467'), {'deck_check': True})
        self.assertEqual(digest.deck_check('79927398713'), {'deck_check': True})

    def test_quay_row(self):
        self.assertEqual(digest.quay_row(0), {'quay_row': '$0.00'})
        self.assertEqual(digest.quay_row(123456), {'quay_row': '$1,234.56'})

    def test_hull_total(self):
        self.assertEqual(digest.hull_total(50, 75), {'hull_total': 50.0})
        self.assertEqual(digest.hull_total(200, 150), {'hull_total': -25.0})
        self.assertEqual(digest.hull_total(3, 4), {'hull_total': 33.33})
