import unittest

from wharf import stock


class Stock(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(stock.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(stock.rle(''), [])
        self.assertEqual(stock.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])

    def test_parse_duration(self):
        self.assertEqual(stock.parse_duration('1h30m'), 5400)
        self.assertEqual(stock.parse_duration('45s'), 45)
        self.assertEqual(stock.parse_duration('2h'), 7200)

    def test_paginate(self):
        self.assertEqual(stock.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(stock.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(stock.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
