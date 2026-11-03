import unittest

from foundry import metrics


class Metrics(unittest.TestCase):
    def test_weighted_mean(self):
        self.assertEqual(metrics.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(metrics.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(metrics.weighted_mean([4], [2]), 4.0)

    def test_dedupe(self):
        self.assertEqual(metrics.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(metrics.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(metrics.dedupe([]), [])
