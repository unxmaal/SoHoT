import unittest

from depot.kitchen import merge_ranges
from depot import kitchen


class Kitchen(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(merge_ranges([(1, 10), (2, 3)]), [(1, 10)])

    def test_moving_average(self):
        self.assertEqual(kitchen.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(kitchen.moving_average([5], 1), [5.0])
