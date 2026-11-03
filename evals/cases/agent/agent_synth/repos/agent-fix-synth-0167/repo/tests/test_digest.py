import unittest

from atlas import digest


class Digest(unittest.TestCase):
    def test_quay_check(self):
        self.assertEqual(digest.quay_check([3, 1, 3, 2, 1]), {'quay_check': [3, 1, 2]})
        self.assertEqual(digest.quay_check(['b', 'a', 'b']), {'quay_check': ['b', 'a']})

    def test_berth_total(self):
        self.assertEqual(digest.berth_total(5, 0, 10), {'berth_total': 5})
        self.assertEqual(digest.berth_total(-3, 0, 10), {'berth_total': 0})

    def test_hull_check(self):
        self.assertEqual(digest.hull_check('OrderTotal'), {'hull_check': 'order_total'})
        self.assertEqual(digest.hull_check('plain'), {'hull_check': 'plain'})

    def test_crate_summary(self):
        self.assertEqual(digest.crate_summary([1, 2, 3]), {'crate_summary': [1, 3, 6]})
        self.assertEqual(digest.crate_summary([]), {'crate_summary': []})

    def test_buoy_row(self):
        self.assertEqual(digest.buoy_row([1, 2, 3, 4], 2), {'buoy_row': [1.5, 2.5, 3.5]})
        self.assertEqual(digest.buoy_row([5], 1), {'buoy_row': [5.0]})
        self.assertEqual(digest.buoy_row([1, 2, 3], 3), {'buoy_row': [2.0]})
