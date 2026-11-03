import unittest

from harbor import stock


class Stock(unittest.TestCase):
    def test_invert(self):
        self.assertEqual(stock.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(stock.invert({}), {})

    def test_is_leap(self):
        self.assertEqual(stock.is_leap(2024), True)
        self.assertEqual(stock.is_leap(1900), False)
