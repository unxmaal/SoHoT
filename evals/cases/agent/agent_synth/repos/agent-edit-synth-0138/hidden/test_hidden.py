import unittest

from orchard import pricing
from orchard import tickets
from orchard import orders
from orchard import weather


class Hidden(unittest.TestCase):
    def test_pricing_is_leap(self):
        self.assertEqual(pricing.is_leap(2024), True)
        self.assertEqual(pricing.is_leap(1900), False)
        self.assertEqual(pricing.is_leap(2000), True)
        self.assertEqual(pricing.is_leap(2023), False)
        self.assertEqual(pricing.is_leap(2400), True)
        self.assertEqual(pricing.is_leap(2100), False)

    def test_pricing_grade(self):
        self.assertEqual(pricing.grade(95), 'A')
        self.assertEqual(pricing.grade(90), 'A')
        self.assertEqual(pricing.grade(85), 'B')
        self.assertEqual(pricing.grade(80), 'B')
        self.assertEqual(pricing.grade(61), 'D')
        self.assertEqual(pricing.grade(59), 'F')
        self.assertEqual(pricing.grade(0), 'F')

    def test_pricing_format_cents(self):
        self.assertEqual(pricing.format_cents(0), '$0.00')
        self.assertEqual(pricing.format_cents(123456), '$1,234.56')
        self.assertEqual(pricing.format_cents(-105), '-$1.05')
        self.assertEqual(pricing.format_cents(5), '$0.05')
        self.assertEqual(pricing.format_cents(100000000), '$1,000,000.00')

    def test_tickets_word_count(self):
        self.assertEqual(tickets.word_count('a b'), 2)
        self.assertEqual(tickets.word_count('  tea  and   milk '), 3)
        self.assertEqual(tickets.word_count(''), 0)
        self.assertEqual(tickets.word_count('one'), 1)

    def test_tickets_running_total(self):
        self.assertEqual(tickets.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(tickets.running_total([]), [])
        self.assertEqual(tickets.running_total([5]), [5])
        self.assertEqual(tickets.running_total([2, -2, 2]), [2, 0, 2])

    def test_tickets_dedupe(self):
        self.assertEqual(tickets.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(tickets.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(tickets.dedupe([]), [])
        self.assertEqual(tickets.dedupe([1, 1, 1]), [1])

    def test_orders_snake_case(self):
        self.assertEqual(orders.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(orders.snake_case('plain'), 'plain')
        self.assertEqual(orders.snake_case('A'), 'a')
        self.assertEqual(orders.snake_case('ShipToCity'), 'ship_to_city')

    def test_orders_moving_average(self):
        self.assertEqual(orders.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(orders.moving_average([5], 1), [5.0])
        self.assertEqual(orders.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(orders.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            orders.moving_average([1, 2], 0)

    def test_orders_median(self):
        self.assertEqual(orders.median([3, 1, 2]), 2)
        self.assertEqual(orders.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(orders.median([5]), 5)
        self.assertEqual(orders.median([1, 2]), 1.5)
        self.assertEqual(orders.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            orders.median([])

    def test_weather_rle(self):
        self.assertEqual(weather.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(weather.rle(''), [])
        self.assertEqual(weather.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(weather.rle('zz'), [('z', 2)])

    def test_weather_parse_duration(self):
        self.assertEqual(weather.parse_duration('1h30m'), 5400)
        self.assertEqual(weather.parse_duration('45s'), 45)
        self.assertEqual(weather.parse_duration('2h'), 7200)
        self.assertEqual(weather.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            weather.parse_duration('')
        with self.assertRaises(ValueError):
            weather.parse_duration('5x')
        self.assertEqual(weather.parse_duration('10m5s'), 605)

    def test_weather_paginate(self):
        self.assertEqual(weather.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(weather.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(weather.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(weather.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            weather.paginate([1, 2], 0, 2)

    def test_feature(self):
        self.assertEqual(pricing.format_cents(123456, symbol='GBP '), 'GBP 1,234.56')
        self.assertEqual(pricing.format_cents(-105, symbol='EUR '), '-EUR 1.05')
