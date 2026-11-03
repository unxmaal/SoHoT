import unittest

from wharf import shipping


class Shipping(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(shipping.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(shipping.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])

    def test_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
