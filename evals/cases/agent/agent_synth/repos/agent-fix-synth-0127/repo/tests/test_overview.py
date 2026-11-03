import unittest

from atlas import overview


class Overview(unittest.TestCase):
    def test_berth_row(self):
        self.assertEqual(overview.berth_row(5, 0, 10), {'berth_row': 5})
        self.assertEqual(overview.berth_row(-3, 0, 10), {'berth_row': 0})

    def test_quay_total(self):
        self.assertEqual(overview.quay_total('OrderTotal'), {'quay_total': 'order_total'})
        self.assertEqual(overview.quay_total('plain'), {'quay_total': 'plain'})
        self.assertEqual(overview.quay_total('A'), {'quay_total': 'a'})

    def test_tide_summary(self):
        self.assertEqual(overview.tide_summary([1, 2, 3, 4], 2), {'tide_summary': [1.5, 2.5, 3.5]})
        self.assertEqual(overview.tide_summary([5], 1), {'tide_summary': [5.0]})

    def test_lantern_entry(self):
        self.assertEqual(overview.lantern_entry(95), {'lantern_entry': 'A'})
        self.assertEqual(overview.lantern_entry(90), {'lantern_entry': 'A'})
