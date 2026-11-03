import unittest

from kiln.stock import window_means
from kiln import stock


class Stock(unittest.TestCase):
    def test_window_means(self):
        self.assertEqual(window_means([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(window_means([5], 1), [5.0])
        self.assertEqual(window_means([1, 2, 3], 3), [2.0])

    def test_percent_change(self):
        self.assertEqual(stock.percent_change(50, 75), 50.0)
        self.assertEqual(stock.percent_change(200, 150), -25.0)
