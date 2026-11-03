import unittest

from beacon import metrics


class Metrics(unittest.TestCase):
    def test_lantern_line(self):
        self.assertEqual(metrics.lantern_line('OrderTotal'), {'lantern_line': 'order_total'})
        self.assertEqual(metrics.lantern_line('plain'), {'lantern_line': 'plain'})

    def test_bucket(self):
        self.assertEqual(metrics.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(metrics.bucket(-1, [0, 5, 10]), 0)
