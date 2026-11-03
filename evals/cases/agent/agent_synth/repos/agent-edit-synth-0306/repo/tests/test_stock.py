import unittest

from quarry import stock


class Stock(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(stock.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(stock.rle(''), [])
        self.assertEqual(stock.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])

    def test_is_leap(self):
        self.assertEqual(stock.is_leap(2024), True)
        self.assertEqual(stock.is_leap(1900), False)
        self.assertEqual(stock.is_leap(2000), True)
