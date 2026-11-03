import unittest

from tally import sensors
from tally import orders
from tally import catalog
from tally import kitchen


class Hidden(unittest.TestCase):
    def test_sensors_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
        self.assertEqual(sensors.percent_change(80, 80), 0.0)
        self.assertEqual(sensors.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            sensors.percent_change(0, 5)
        self.assertEqual(sensors.percent_change(-10, -5), -50.0)

    def test_sensors_grade(self):
        self.assertEqual(sensors.grade(95), 'A')
        self.assertEqual(sensors.grade(90), 'A')
        self.assertEqual(sensors.grade(85), 'B')
        self.assertEqual(sensors.grade(80), 'B')
        self.assertEqual(sensors.grade(61), 'D')
        self.assertEqual(sensors.grade(59), 'F')
        self.assertEqual(sensors.grade(0), 'F')

    def test_sensors_word_count(self):
        self.assertEqual(sensors.word_count('a b'), 2)
        self.assertEqual(sensors.word_count('  tea  and   milk '), 3)
        self.assertEqual(sensors.word_count(''), 0)
        self.assertEqual(sensors.word_count('one'), 1)

    def test_orders_invert(self):
        self.assertEqual(orders.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(orders.invert({}), {})
        self.assertEqual(orders.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(orders.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_orders_merge_ranges(self):
        self.assertEqual(orders.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(orders.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(orders.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(orders.merge_ranges([]), [])
        self.assertEqual(orders.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_catalog_paginate(self):
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(catalog.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            catalog.paginate([1, 2], 0, 2)

    def test_catalog_top_n(self):
        self.assertEqual(catalog.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(catalog.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(catalog.top_n({}, 2), [])
        self.assertEqual(catalog.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_kitchen_truncate_words(self):
        self.assertEqual(kitchen.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(kitchen.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(kitchen.truncate_words('', 3), '')
        self.assertEqual(kitchen.truncate_words('one two three', 1), 'one...')

    def test_kitchen_weighted_mean(self):
        self.assertEqual(kitchen.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(kitchen.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(kitchen.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            kitchen.weighted_mean([5, 5], [0, 0])
        self.assertEqual(kitchen.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_kitchen_parse_duration(self):
        self.assertEqual(kitchen.parse_duration('1h30m'), 5400)
        self.assertEqual(kitchen.parse_duration('45s'), 45)
        self.assertEqual(kitchen.parse_duration('2h'), 7200)
        self.assertEqual(kitchen.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            kitchen.parse_duration('')
        with self.assertRaises(ValueError):
            kitchen.parse_duration('5x')
        self.assertEqual(kitchen.parse_duration('10m5s'), 605)
