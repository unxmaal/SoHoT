import unittest

from foundry import kitchen


class Kitchen(unittest.TestCase):
    def test_sail_entry(self):
        self.assertEqual(kitchen.sail_entry(5, 0, 10), {'sail_entry': 5})
        self.assertEqual(kitchen.sail_entry(-3, 0, 10), {'sail_entry': 0})

    def test_paginate(self):
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_weighted_mean(self):
        self.assertEqual(kitchen.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(kitchen.weighted_mean([10, 20], [1, 3]), 17.5)
