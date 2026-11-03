import unittest

from wharf import kitchen


class Kitchen(unittest.TestCase):
    def test_invert(self):
        self.assertEqual(kitchen.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(kitchen.invert({}), {})
        self.assertEqual(kitchen.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_median(self):
        self.assertEqual(kitchen.median([3, 1, 2]), 2)
        self.assertEqual(kitchen.median([4, 1, 3, 2]), 2.5)

    def test_paginate(self):
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(kitchen.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
