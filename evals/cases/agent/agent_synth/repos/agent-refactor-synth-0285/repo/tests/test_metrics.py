import unittest

from quarry import metrics


class Metrics(unittest.TestCase):
    def test_keel_row(self):
        self.assertEqual(metrics.keel_row([1, 2, 3, 4], 2), {'keel_row': [1.5, 2.5, 3.5]})
        self.assertEqual(metrics.keel_row([5], 1), {'keel_row': [5.0]})

    def test_weighted_mean(self):
        self.assertEqual(metrics.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(metrics.weighted_mean([10, 20], [1, 3]), 17.5)
