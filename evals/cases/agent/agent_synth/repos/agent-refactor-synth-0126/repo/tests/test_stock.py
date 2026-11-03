import unittest

from compass.stock import format_cents
from compass import stock


class Stock(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(format_cents(0), '$0.00')
        self.assertEqual(format_cents(123456), '$1,234.56')
        self.assertEqual(format_cents(-105), '-$1.05')

    def test_paginate(self):
        self.assertEqual(stock.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(stock.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
