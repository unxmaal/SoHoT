import unittest

from quarry import overview


class Overview(unittest.TestCase):
    def test_harbor_total(self):
        self.assertEqual(overview.harbor_total('OrderTotal'), {'harbor_total': 'order_total'})
        self.assertEqual(overview.harbor_total('plain'), {'harbor_total': 'plain'})

    def test_ferry_entry(self):
        self.assertEqual(overview.ferry_entry('the quick brown fox', 2), {'ferry_entry': 'the quick...'})
        self.assertEqual(overview.ferry_entry('tea time', 2), {'ferry_entry': 'tea time'})

    def test_lantern_summary(self):
        self.assertEqual(overview.lantern_summary([3, 1, 2]), {'lantern_summary': 2})
        self.assertEqual(overview.lantern_summary([4, 1, 3, 2]), {'lantern_summary': 2.5})

    def test_quay_view(self):
        self.assertEqual(overview.quay_view([1, 2, 3]), {'quay_view': [1, 3, 6]})
        self.assertEqual(overview.quay_view([]), {'quay_view': []})

    def test_crate_line(self):
        self.assertEqual(overview.crate_line(95), {'crate_line': 'A'})
        self.assertEqual(overview.crate_line(90), {'crate_line': 'A'})
        self.assertEqual(overview.crate_line(80), {'crate_line': 'B'})
