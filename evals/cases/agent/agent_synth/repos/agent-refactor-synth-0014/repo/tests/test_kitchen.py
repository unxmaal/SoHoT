import unittest

from meadow import kitchen


class Kitchen(unittest.TestCase):
    def test_berth_line(self):
        self.assertEqual(kitchen.berth_line(5, [0, 5, 10]), {'berth_line': 2})
        self.assertEqual(kitchen.berth_line(-1, [0, 5, 10]), {'berth_line': 0})

    def test_paginate(self):
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_weighted_mean(self):
        self.assertEqual(kitchen.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(kitchen.weighted_mean([10, 20], [1, 3]), 17.5)
