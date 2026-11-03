import unittest

from meadow import metrics


class Metrics(unittest.TestCase):
    def test_invert(self):
        self.assertEqual(metrics.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(metrics.invert({}), {})

    def test_paginate(self):
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
