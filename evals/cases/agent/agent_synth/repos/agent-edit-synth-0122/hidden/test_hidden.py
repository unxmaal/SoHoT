import unittest

from harbor import pricing
from harbor import ledger
from harbor import fleet
from harbor import weather


class Hidden(unittest.TestCase):
    def test_pricing_rle(self):
        self.assertEqual(pricing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(pricing.rle(''), [])
        self.assertEqual(pricing.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(pricing.rle('zz'), [('z', 2)])

    def test_pricing_grade(self):
        self.assertEqual(pricing.grade(95), 'A')
        self.assertEqual(pricing.grade(90), 'A')
        self.assertEqual(pricing.grade(85), 'B')
        self.assertEqual(pricing.grade(80), 'B')
        self.assertEqual(pricing.grade(61), 'D')
        self.assertEqual(pricing.grade(59), 'F')
        self.assertEqual(pricing.grade(0), 'F')

    def test_pricing_parse_duration(self):
        self.assertEqual(pricing.parse_duration('1h30m'), 5400)
        self.assertEqual(pricing.parse_duration('45s'), 45)
        self.assertEqual(pricing.parse_duration('2h'), 7200)
        self.assertEqual(pricing.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            pricing.parse_duration('')
        with self.assertRaises(ValueError):
            pricing.parse_duration('5x')
        self.assertEqual(pricing.parse_duration('10m5s'), 605)

    def test_ledger_luhn_valid(self):
        self.assertEqual(ledger.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(ledger.luhn_valid('79927398713'), True)
        self.assertEqual(ledger.luhn_valid('79927398710'), False)
        self.assertEqual(ledger.luhn_valid(''), False)
        self.assertEqual(ledger.luhn_valid('059'), True)

    def test_ledger_dedupe(self):
        self.assertEqual(ledger.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(ledger.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(ledger.dedupe([]), [])
        self.assertEqual(ledger.dedupe([1, 1, 1]), [1])

    def test_fleet_snake_case(self):
        self.assertEqual(fleet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(fleet.snake_case('plain'), 'plain')
        self.assertEqual(fleet.snake_case('A'), 'a')
        self.assertEqual(fleet.snake_case('ShipToCity'), 'ship_to_city')

    def test_fleet_percent_change(self):
        self.assertEqual(fleet.percent_change(50, 75), 50.0)
        self.assertEqual(fleet.percent_change(200, 150), -25.0)
        self.assertEqual(fleet.percent_change(80, 80), 0.0)
        self.assertEqual(fleet.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            fleet.percent_change(0, 5)
        self.assertEqual(fleet.percent_change(-10, -5), -50.0)

    def test_fleet_word_count(self):
        self.assertEqual(fleet.word_count('a b'), 2)
        self.assertEqual(fleet.word_count('  tea  and   milk '), 3)
        self.assertEqual(fleet.word_count(''), 0)
        self.assertEqual(fleet.word_count('one'), 1)

    def test_weather_paginate(self):
        self.assertEqual(weather.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(weather.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(weather.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(weather.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            weather.paginate([1, 2], 0, 2)

    def test_weather_merge_ranges(self):
        self.assertEqual(weather.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(weather.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(weather.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(weather.merge_ranges([]), [])
        self.assertEqual(weather.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_weather_invert(self):
        self.assertEqual(weather.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(weather.invert({}), {})
        self.assertEqual(weather.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(weather.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_feature(self):
        self.assertEqual(fleet.word_count('a tea and milk', min_length=3), 3)
        self.assertEqual(fleet.word_count('go on', min_length=5), 0)
