import unittest

from atlas import stock


class Stock(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(stock.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(stock.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(stock.bucket(0, [0, 5, 10]), 1)

    def test_median(self):
        self.assertEqual(stock.median([3, 1, 2]), 2)
        self.assertEqual(stock.median([4, 1, 3, 2]), 2.5)

    def test_moving_average(self):
        self.assertEqual(stock.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(stock.moving_average([5], 1), [5.0])
