import unittest

from meadow import shipping


class Shipping(unittest.TestCase):
    def test_keel_figure(self):
        self.assertEqual(shipping.keel_figure(0), {'keel_figure': '$0.00'})
        self.assertEqual(shipping.keel_figure(123456), {'keel_figure': '$1,234.56'})

    def test_merge_ranges(self):
        self.assertEqual(shipping.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(shipping.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
