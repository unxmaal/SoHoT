import unittest

from quarry import tickets
from quarry import routes


class Hidden(unittest.TestCase):
    def test_tickets_snake_case(self):
        self.assertEqual(tickets.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(tickets.snake_case('plain'), 'plain')
        self.assertEqual(tickets.snake_case('A'), 'a')
        self.assertEqual(tickets.snake_case('ShipToCity'), 'ship_to_city')

    def test_tickets_format_cents(self):
        self.assertEqual(tickets.format_cents(0), '$0.00')
        self.assertEqual(tickets.format_cents(123456), '$1,234.56')
        self.assertEqual(tickets.format_cents(-105), '-$1.05')
        self.assertEqual(tickets.format_cents(5), '$0.05')
        self.assertEqual(tickets.format_cents(100000000), '$1,000,000.00')

    def test_tickets_percent_change(self):
        self.assertEqual(tickets.percent_change(50, 75), 50.0)
        self.assertEqual(tickets.percent_change(200, 150), -25.0)
        self.assertEqual(tickets.percent_change(80, 80), 0.0)
        self.assertEqual(tickets.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            tickets.percent_change(0, 5)
        self.assertEqual(tickets.percent_change(-10, -5), -50.0)

    def test_routes_is_leap(self):
        self.assertEqual(routes.is_leap(2024), True)
        self.assertEqual(routes.is_leap(1900), False)
        self.assertEqual(routes.is_leap(2000), True)
        self.assertEqual(routes.is_leap(2023), False)
        self.assertEqual(routes.is_leap(2400), True)
        self.assertEqual(routes.is_leap(2100), False)

    def test_routes_chunk(self):
        self.assertEqual(routes.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(routes.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(routes.chunk([], 3), [])
        self.assertEqual(routes.chunk(['a'], 1), [['a']])
        self.assertEqual(routes.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            routes.chunk([1, 2], 0)

    def test_feature(self):
        self.assertEqual(routes.chunk([1, 2, 3], 2, pad=0), [[1, 2], [3, 0]])
        self.assertEqual(routes.chunk([1, 2, 3, 4], 2, pad=0), [[1, 2], [3, 4]])
        self.assertEqual(routes.chunk(['a', 'b', 'c'], 5, pad='-'), [['a', 'b', 'c', '-', '-']])
