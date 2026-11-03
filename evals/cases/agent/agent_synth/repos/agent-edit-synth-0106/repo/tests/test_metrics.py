import unittest

from wharf import metrics


class Metrics(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(metrics.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(metrics.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(metrics.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])

    def test_invert(self):
        self.assertEqual(metrics.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(metrics.invert({}), {})
        self.assertEqual(metrics.invert({'x': 'y'}), {'y': ['x']})
