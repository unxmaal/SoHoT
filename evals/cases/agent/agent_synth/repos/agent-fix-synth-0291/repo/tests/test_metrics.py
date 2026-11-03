import unittest

from atlas import metrics


class Metrics(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(metrics.clamp(5, 0, 10), 5)
        self.assertEqual(metrics.clamp(-3, 0, 10), 0)
        self.assertEqual(metrics.clamp(15, 0, 10), 10)

    def test_running_total(self):
        self.assertEqual(metrics.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(metrics.running_total([]), [])

    def test_invert(self):
        self.assertEqual(metrics.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(metrics.invert({}), {})
