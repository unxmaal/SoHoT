import unittest

from wharf import metrics


class Metrics(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(metrics.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(metrics.bucket(-1, [0, 5, 10]), 0)

    def test_weighted_mean(self):
        self.assertEqual(metrics.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(metrics.weighted_mean([10, 20], [1, 3]), 17.5)
