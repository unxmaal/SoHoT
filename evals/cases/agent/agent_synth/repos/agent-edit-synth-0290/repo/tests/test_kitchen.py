import unittest

from granary import kitchen


class Kitchen(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(kitchen.percent_change(50, 75), 50.0)
        self.assertEqual(kitchen.percent_change(200, 150), -25.0)
        self.assertEqual(kitchen.percent_change(80, 80), 0.0)

    def test_dedupe(self):
        self.assertEqual(kitchen.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(kitchen.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(kitchen.dedupe([]), [])

    def test_paginate(self):
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
