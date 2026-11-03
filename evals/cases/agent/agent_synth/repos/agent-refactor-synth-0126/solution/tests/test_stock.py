import unittest

from compass.stock import money
from compass import stock


class Stock(unittest.TestCase):
    def test_money(self):
        self.assertEqual(money(0), '$0.00')
        self.assertEqual(money(123456), '$1,234.56')
        self.assertEqual(money(-105), '-$1.05')

    def test_paginate(self):
        self.assertEqual(stock.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(stock.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
