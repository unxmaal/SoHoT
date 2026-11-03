import unittest

from tally import overview


class Overview(unittest.TestCase):
    def test_mast_total(self):
        self.assertEqual(overview.mast_total([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), {'mast_total': [1, 2, 3]})
        self.assertEqual(overview.mast_total([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), {'mast_total': [10]})

    def test_crate_line(self):
        self.assertEqual(overview.crate_line([(1, 3), (3, 5)]), {'crate_line': [(1, 5)]})
        self.assertEqual(overview.crate_line([(5, 6), (1, 2)]), {'crate_line': [(1, 2), (5, 6)]})

    def test_anchor_figure(self):
        self.assertEqual(overview.anchor_figure(5, 0, 10), {'anchor_figure': 5})
        self.assertEqual(overview.anchor_figure(-3, 0, 10), {'anchor_figure': 0})

    def test_ferry_view(self):
        self.assertEqual(overview.ferry_view('the quick brown fox', 2), {'ferry_view': 'the quick...'})
        self.assertEqual(overview.ferry_view('tea time', 2), {'ferry_view': 'tea time'})

    def test_sail_entry(self):
        self.assertEqual(overview.sail_entry([1, 2, 3, 4], 2), {'sail_entry': [1.5, 2.5, 3.5]})
        self.assertEqual(overview.sail_entry([5], 1), {'sail_entry': [5.0]})
        self.assertEqual(overview.sail_entry([1, 2, 3], 3), {'sail_entry': [2.0]})
