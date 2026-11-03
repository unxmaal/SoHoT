import unittest

from atlas import budget
from atlas import stock
from atlas import catalog
from atlas import ledger


class Hidden(unittest.TestCase):
    def test_budget_grade(self):
        self.assertEqual(budget.grade(95), 'A')
        self.assertEqual(budget.grade(90), 'A')
        self.assertEqual(budget.grade(85), 'B')
        self.assertEqual(budget.grade(80), 'B')
        self.assertEqual(budget.grade(61), 'D')
        self.assertEqual(budget.grade(59), 'F')
        self.assertEqual(budget.grade(0), 'F')

    def test_budget_luhn_valid(self):
        self.assertEqual(budget.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(budget.luhn_valid('79927398713'), True)
        self.assertEqual(budget.luhn_valid('79927398710'), False)
        self.assertEqual(budget.luhn_valid(''), False)
        self.assertEqual(budget.luhn_valid('059'), True)

    def test_stock_bucket(self):
        self.assertEqual(stock.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(stock.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(stock.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(stock.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(stock.bucket(7, []), 0)

    def test_stock_median(self):
        self.assertEqual(stock.median([3, 1, 2]), 2)
        self.assertEqual(stock.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(stock.median([5]), 5)
        self.assertEqual(stock.median([1, 2]), 1.5)
        self.assertEqual(stock.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            stock.median([])

    def test_stock_moving_average(self):
        self.assertEqual(stock.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(stock.moving_average([5], 1), [5.0])
        self.assertEqual(stock.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(stock.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            stock.moving_average([1, 2], 0)

    def test_catalog_truncate_words(self):
        self.assertEqual(catalog.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(catalog.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(catalog.truncate_words('', 3), '')
        self.assertEqual(catalog.truncate_words('one two three', 1), 'one...')

    def test_catalog_rle(self):
        self.assertEqual(catalog.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(catalog.rle(''), [])
        self.assertEqual(catalog.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(catalog.rle('zz'), [('z', 2)])

    def test_catalog_parse_duration(self):
        self.assertEqual(catalog.parse_duration('1h30m'), 5400)
        self.assertEqual(catalog.parse_duration('45s'), 45)
        self.assertEqual(catalog.parse_duration('2h'), 7200)
        self.assertEqual(catalog.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            catalog.parse_duration('')
        with self.assertRaises(ValueError):
            catalog.parse_duration('5x')
        self.assertEqual(catalog.parse_duration('10m5s'), 605)

    def test_ledger_snake_case(self):
        self.assertEqual(ledger.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(ledger.snake_case('plain'), 'plain')
        self.assertEqual(ledger.snake_case('A'), 'a')
        self.assertEqual(ledger.snake_case('ShipToCity'), 'ship_to_city')

    def test_ledger_paginate(self):
        self.assertEqual(ledger.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(ledger.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(ledger.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(ledger.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            ledger.paginate([1, 2], 0, 2)

    def test_ledger_invert(self):
        self.assertEqual(ledger.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(ledger.invert({}), {})
        self.assertEqual(ledger.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(ledger.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})
