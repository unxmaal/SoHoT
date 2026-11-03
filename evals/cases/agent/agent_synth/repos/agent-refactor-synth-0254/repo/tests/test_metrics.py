import unittest

from depot import metrics


class Metrics(unittest.TestCase):
    def test_lantern_view(self):
        self.assertEqual(metrics.lantern_view([(1, 3), (3, 5)]), {'lantern_view': [(1, 5)]})
        self.assertEqual(metrics.lantern_view([(5, 6), (1, 2)]), {'lantern_view': [(1, 2), (5, 6)]})

    def test_paginate(self):
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
