import unittest

from orchard import pricing


class Pricing(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(pricing.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(pricing.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])

    def test_paginate(self):
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(pricing.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_clamp(self):
        self.assertEqual(pricing.clamp(5, 0, 10), 5)
        self.assertEqual(pricing.clamp(-3, 0, 10), 0)
