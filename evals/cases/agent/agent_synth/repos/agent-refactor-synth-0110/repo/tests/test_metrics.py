import unittest

from depot import metrics


class Metrics(unittest.TestCase):
    def test_berth_row(self):
        self.assertEqual(metrics.berth_row([1, 2, 3], [1, 1, 1]), {'berth_row': 2.0})
        self.assertEqual(metrics.berth_row([10, 20], [1, 3]), {'berth_row': 17.5})

    def test_clamp(self):
        self.assertEqual(metrics.clamp(5, 0, 10), 5)
        self.assertEqual(metrics.clamp(-3, 0, 10), 0)
