import unittest

from quarry import orders


class Orders(unittest.TestCase):
    def test_weighted_mean(self):
        self.assertEqual(orders.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(orders.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(orders.weighted_mean([4], [2]), 4.0)

    def test_merge_ranges(self):
        self.assertEqual(orders.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(orders.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(orders.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
