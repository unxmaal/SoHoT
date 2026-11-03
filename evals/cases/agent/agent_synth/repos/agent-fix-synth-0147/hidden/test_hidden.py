import unittest

from compass import shipping
from compass import fleet
from compass import tickets
from compass import sensors


class Hidden(unittest.TestCase):
    def test_shipping_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(shipping.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            shipping.paginate([1, 2], 0, 2)

    def test_shipping_rle(self):
        self.assertEqual(shipping.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(shipping.rle(''), [])
        self.assertEqual(shipping.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(shipping.rle('zz'), [('z', 2)])

    def test_fleet_median(self):
        self.assertEqual(fleet.median([3, 1, 2]), 2)
        self.assertEqual(fleet.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(fleet.median([5]), 5)
        self.assertEqual(fleet.median([1, 2]), 1.5)
        self.assertEqual(fleet.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            fleet.median([])

    def test_fleet_word_count(self):
        self.assertEqual(fleet.word_count('a b'), 2)
        self.assertEqual(fleet.word_count('  tea  and   milk '), 3)
        self.assertEqual(fleet.word_count(''), 0)
        self.assertEqual(fleet.word_count('one'), 1)

    def test_fleet_weighted_mean(self):
        self.assertEqual(fleet.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(fleet.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(fleet.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            fleet.weighted_mean([5, 5], [0, 0])
        self.assertEqual(fleet.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_tickets_chunk(self):
        self.assertEqual(tickets.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(tickets.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(tickets.chunk([], 3), [])
        self.assertEqual(tickets.chunk(['a'], 1), [['a']])
        self.assertEqual(tickets.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            tickets.chunk([1, 2], 0)

    def test_tickets_snake_case(self):
        self.assertEqual(tickets.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(tickets.snake_case('plain'), 'plain')
        self.assertEqual(tickets.snake_case('A'), 'a')
        self.assertEqual(tickets.snake_case('ShipToCity'), 'ship_to_city')

    def test_sensors_clamp(self):
        self.assertEqual(sensors.clamp(5, 0, 10), 5)
        self.assertEqual(sensors.clamp(-3, 0, 10), 0)
        self.assertEqual(sensors.clamp(15, 0, 10), 10)
        self.assertEqual(sensors.clamp(10, 0, 10), 10)
        self.assertEqual(sensors.clamp(0, 0, 10), 0)
        self.assertEqual(sensors.clamp(7, 7, 7), 7)
        self.assertEqual(sensors.clamp(-20, -30, -10), -20)

    def test_sensors_format_cents(self):
        self.assertEqual(sensors.format_cents(0), '$0.00')
        self.assertEqual(sensors.format_cents(123456), '$1,234.56')
        self.assertEqual(sensors.format_cents(-105), '-$1.05')
        self.assertEqual(sensors.format_cents(5), '$0.05')
        self.assertEqual(sensors.format_cents(100000000), '$1,000,000.00')

    def test_sensors_dedupe(self):
        self.assertEqual(sensors.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(sensors.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(sensors.dedupe([]), [])
        self.assertEqual(sensors.dedupe([1, 1, 1]), [1])
