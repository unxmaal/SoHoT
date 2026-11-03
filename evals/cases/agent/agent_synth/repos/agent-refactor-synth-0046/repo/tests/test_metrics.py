import unittest

from kiln import metrics


class Metrics(unittest.TestCase):
    def test_berth_total(self):
        self.assertEqual(metrics.berth_total([1, 2, 3, 4], 2), {'berth_total': [1.5, 2.5, 3.5]})
        self.assertEqual(metrics.berth_total([5], 1), {'berth_total': [5.0]})

    def test_invert(self):
        self.assertEqual(metrics.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(metrics.invert({}), {})

    def test_top_n(self):
        self.assertEqual(metrics.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(metrics.top_n({'a': 1}, 5), ['a'])
