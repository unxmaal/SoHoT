import unittest

from depot import orders
from depot import tickets
from depot import kitchen
from depot import stock


class Hidden(unittest.TestCase):
    def test_orders_is_leap(self):
        self.assertEqual(orders.is_leap(2024), True)
        self.assertEqual(orders.is_leap(1900), False)
        self.assertEqual(orders.is_leap(2000), True)
        self.assertEqual(orders.is_leap(2023), False)
        self.assertEqual(orders.is_leap(2400), True)
        self.assertEqual(orders.is_leap(2100), False)

    def test_orders_weighted_mean(self):
        self.assertEqual(orders.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(orders.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(orders.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            orders.weighted_mean([5, 5], [0, 0])
        self.assertEqual(orders.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_orders_clamp(self):
        self.assertEqual(orders.clamp(5, 0, 10), 5)
        self.assertEqual(orders.clamp(-3, 0, 10), 0)
        self.assertEqual(orders.clamp(15, 0, 10), 10)
        self.assertEqual(orders.clamp(10, 0, 10), 10)
        self.assertEqual(orders.clamp(0, 0, 10), 0)
        self.assertEqual(orders.clamp(7, 7, 7), 7)
        self.assertEqual(orders.clamp(-20, -30, -10), -20)

    def test_tickets_percent_change(self):
        self.assertEqual(tickets.percent_change(50, 75), 50.0)
        self.assertEqual(tickets.percent_change(200, 150), -25.0)
        self.assertEqual(tickets.percent_change(80, 80), 0.0)
        self.assertEqual(tickets.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            tickets.percent_change(0, 5)
        self.assertEqual(tickets.percent_change(-10, -5), -50.0)

    def test_tickets_invert(self):
        self.assertEqual(tickets.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(tickets.invert({}), {})
        self.assertEqual(tickets.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(tickets.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_tickets_word_count(self):
        self.assertEqual(tickets.word_count('a b'), 2)
        self.assertEqual(tickets.word_count('  tea  and   milk '), 3)
        self.assertEqual(tickets.word_count(''), 0)
        self.assertEqual(tickets.word_count('one'), 1)

    def test_kitchen_grade(self):
        self.assertEqual(kitchen.grade(95), 'A')
        self.assertEqual(kitchen.grade(90), 'A')
        self.assertEqual(kitchen.grade(85), 'B')
        self.assertEqual(kitchen.grade(80), 'B')
        self.assertEqual(kitchen.grade(61), 'D')
        self.assertEqual(kitchen.grade(59), 'F')
        self.assertEqual(kitchen.grade(0), 'F')

    def test_kitchen_luhn_valid(self):
        self.assertEqual(kitchen.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(kitchen.luhn_valid('79927398713'), True)
        self.assertEqual(kitchen.luhn_valid('79927398710'), False)
        self.assertEqual(kitchen.luhn_valid(''), False)
        self.assertEqual(kitchen.luhn_valid('059'), True)

    def test_kitchen_format_cents(self):
        self.assertEqual(kitchen.format_cents(0), '$0.00')
        self.assertEqual(kitchen.format_cents(123456), '$1,234.56')
        self.assertEqual(kitchen.format_cents(-105), '-$1.05')
        self.assertEqual(kitchen.format_cents(5), '$0.05')
        self.assertEqual(kitchen.format_cents(100000000), '$1,000,000.00')

    def test_stock_chunk(self):
        self.assertEqual(stock.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(stock.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(stock.chunk([], 3), [])
        self.assertEqual(stock.chunk(['a'], 1), [['a']])
        self.assertEqual(stock.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            stock.chunk([1, 2], 0)

    def test_stock_snake_case(self):
        self.assertEqual(stock.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(stock.snake_case('plain'), 'plain')
        self.assertEqual(stock.snake_case('A'), 'a')
        self.assertEqual(stock.snake_case('ShipToCity'), 'ship_to_city')
