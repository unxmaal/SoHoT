import unittest

from depot import metrics


class Metrics(unittest.TestCase):
    def test_dock_line(self):
        self.assertEqual(metrics.dock_line(95), {'dock_line': 'A'})
        self.assertEqual(metrics.dock_line(90), {'dock_line': 'A'})

    def test_median(self):
        self.assertEqual(metrics.median([3, 1, 2]), 2)
        self.assertEqual(metrics.median([4, 1, 3, 2]), 2.5)
