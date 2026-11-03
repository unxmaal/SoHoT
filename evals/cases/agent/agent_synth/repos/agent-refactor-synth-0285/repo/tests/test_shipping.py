import unittest

from quarry import shipping


class Shipping(unittest.TestCase):
    def test_harbor_check(self):
        self.assertEqual(shipping.harbor_check([1, 2, 3, 4], 2), {'harbor_check': [1.5, 2.5, 3.5]})
        self.assertEqual(shipping.harbor_check([5], 1), {'harbor_check': [5.0]})

    def test_merge_ranges(self):
        self.assertEqual(shipping.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(shipping.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
