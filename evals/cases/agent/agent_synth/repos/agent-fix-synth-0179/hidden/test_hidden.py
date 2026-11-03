import unittest

from orchard import orders
from orchard import tickets
from orchard import sensors


class Hidden(unittest.TestCase):
    def test_orders_word_count(self):
        self.assertEqual(orders.word_count('a b'), 2)
        self.assertEqual(orders.word_count('  tea  and   milk '), 3)
        self.assertEqual(orders.word_count(''), 0)
        self.assertEqual(orders.word_count('one'), 1)

    def test_orders_weighted_mean(self):
        self.assertEqual(orders.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(orders.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(orders.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            orders.weighted_mean([5, 5], [0, 0])
        self.assertEqual(orders.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_tickets_parse_duration(self):
        self.assertEqual(tickets.parse_duration('1h30m'), 5400)
        self.assertEqual(tickets.parse_duration('45s'), 45)
        self.assertEqual(tickets.parse_duration('2h'), 7200)
        self.assertEqual(tickets.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            tickets.parse_duration('')
        with self.assertRaises(ValueError):
            tickets.parse_duration('5x')
        self.assertEqual(tickets.parse_duration('10m5s'), 605)

    def test_tickets_top_n(self):
        self.assertEqual(tickets.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(tickets.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(tickets.top_n({}, 2), [])
        self.assertEqual(tickets.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_tickets_median(self):
        self.assertEqual(tickets.median([3, 1, 2]), 2)
        self.assertEqual(tickets.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(tickets.median([5]), 5)
        self.assertEqual(tickets.median([1, 2]), 1.5)
        self.assertEqual(tickets.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            tickets.median([])

    def test_sensors_paginate(self):
        self.assertEqual(sensors.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(sensors.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(sensors.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(sensors.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            sensors.paginate([1, 2], 0, 2)

    def test_sensors_dedupe(self):
        self.assertEqual(sensors.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(sensors.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(sensors.dedupe([]), [])
        self.assertEqual(sensors.dedupe([1, 1, 1]), [1])

    def test_sensors_moving_average(self):
        self.assertEqual(sensors.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(sensors.moving_average([5], 1), [5.0])
        self.assertEqual(sensors.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(sensors.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            sensors.moving_average([1, 2], 0)
