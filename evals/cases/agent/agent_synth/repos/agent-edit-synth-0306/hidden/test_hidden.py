import unittest

from quarry import budget
from quarry import routes
from quarry import shipping
from quarry import stock


class Hidden(unittest.TestCase):
    def test_budget_paginate(self):
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(budget.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            budget.paginate([1, 2], 0, 2)

    def test_budget_format_cents(self):
        self.assertEqual(budget.format_cents(0), '$0.00')
        self.assertEqual(budget.format_cents(123456), '$1,234.56')
        self.assertEqual(budget.format_cents(-105), '-$1.05')
        self.assertEqual(budget.format_cents(5), '$0.05')
        self.assertEqual(budget.format_cents(100000000), '$1,000,000.00')

    def test_routes_snake_case(self):
        self.assertEqual(routes.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(routes.snake_case('plain'), 'plain')
        self.assertEqual(routes.snake_case('A'), 'a')
        self.assertEqual(routes.snake_case('ShipToCity'), 'ship_to_city')

    def test_routes_top_n(self):
        self.assertEqual(routes.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(routes.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(routes.top_n({}, 2), [])
        self.assertEqual(routes.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_shipping_luhn_valid(self):
        self.assertEqual(shipping.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(shipping.luhn_valid('79927398713'), True)
        self.assertEqual(shipping.luhn_valid('79927398710'), False)
        self.assertEqual(shipping.luhn_valid(''), False)
        self.assertEqual(shipping.luhn_valid('059'), True)

    def test_shipping_running_total(self):
        self.assertEqual(shipping.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(shipping.running_total([]), [])
        self.assertEqual(shipping.running_total([5]), [5])
        self.assertEqual(shipping.running_total([2, -2, 2]), [2, 0, 2])

    def test_shipping_invert(self):
        self.assertEqual(shipping.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(shipping.invert({}), {})
        self.assertEqual(shipping.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(shipping.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_stock_rle(self):
        self.assertEqual(stock.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(stock.rle(''), [])
        self.assertEqual(stock.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(stock.rle('zz'), [('z', 2)])

    def test_stock_is_leap(self):
        self.assertEqual(stock.is_leap(2024), True)
        self.assertEqual(stock.is_leap(1900), False)
        self.assertEqual(stock.is_leap(2000), True)
        self.assertEqual(stock.is_leap(2023), False)
        self.assertEqual(stock.is_leap(2400), True)
        self.assertEqual(stock.is_leap(2100), False)

    def test_feature(self):
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], -1, 3), [10])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9], -1, 3), [7, 8, 9])
        self.assertEqual(budget.paginate([], -1, 4), [])
