import unittest

from kiln.stock import moving_average
from kiln import stock


class Stock(unittest.TestCase):
    def test_moving_average(self):
        self.assertEqual(moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(moving_average([5], 1), [5.0])
        self.assertEqual(moving_average([1, 2, 3], 3), [2.0])

    def test_percent_change(self):
        self.assertEqual(stock.percent_change(50, 75), 50.0)
        self.assertEqual(stock.percent_change(200, 150), -25.0)
