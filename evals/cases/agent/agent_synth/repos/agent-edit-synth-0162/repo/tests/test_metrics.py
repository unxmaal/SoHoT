import unittest

from depot import metrics


class Metrics(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(metrics.clamp(5, 0, 10), 5)
        self.assertEqual(metrics.clamp(-3, 0, 10), 0)
        self.assertEqual(metrics.clamp(15, 0, 10), 10)

    def test_median(self):
        self.assertEqual(metrics.median([3, 1, 2]), 2)
        self.assertEqual(metrics.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(metrics.median([5]), 5)
