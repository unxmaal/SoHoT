import unittest

from foundry import catalog
from foundry import weather
from foundry import metrics


class Hidden(unittest.TestCase):
    def test_catalog_rle(self):
        self.assertEqual(catalog.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(catalog.rle(''), [])
        self.assertEqual(catalog.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(catalog.rle('zz'), [('z', 2)])

    def test_catalog_percent_change(self):
        self.assertEqual(catalog.percent_change(50, 75), 50.0)
        self.assertEqual(catalog.percent_change(200, 150), -25.0)
        self.assertEqual(catalog.percent_change(80, 80), 0.0)
        self.assertEqual(catalog.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            catalog.percent_change(0, 5)
        self.assertEqual(catalog.percent_change(-10, -5), -50.0)

    def test_catalog_top_n(self):
        self.assertEqual(catalog.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(catalog.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(catalog.top_n({}, 2), [])
        self.assertEqual(catalog.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_weather_word_count(self):
        self.assertEqual(weather.word_count('a b'), 2)
        self.assertEqual(weather.word_count('  tea  and   milk '), 3)
        self.assertEqual(weather.word_count(''), 0)
        self.assertEqual(weather.word_count('one'), 1)

    def test_weather_dedupe(self):
        self.assertEqual(weather.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(weather.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(weather.dedupe([]), [])
        self.assertEqual(weather.dedupe([1, 1, 1]), [1])

    def test_metrics_parse_duration(self):
        self.assertEqual(metrics.parse_duration('1h30m'), 5400)
        self.assertEqual(metrics.parse_duration('45s'), 45)
        self.assertEqual(metrics.parse_duration('2h'), 7200)
        self.assertEqual(metrics.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            metrics.parse_duration('')
        with self.assertRaises(ValueError):
            metrics.parse_duration('5x')
        self.assertEqual(metrics.parse_duration('10m5s'), 605)

    def test_metrics_paginate(self):
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(metrics.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            metrics.paginate([1, 2], 0, 2)

    def test_metrics_snake_case(self):
        self.assertEqual(metrics.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(metrics.snake_case('plain'), 'plain')
        self.assertEqual(metrics.snake_case('A'), 'a')
        self.assertEqual(metrics.snake_case('ShipToCity'), 'ship_to_city')

    def test_feature(self):
        self.assertEqual(weather.dedupe(['Tea', 'tea', 'Milk', 'TEA'], ignore_case=True), ['Tea', 'Milk'])
        self.assertEqual(weather.dedupe(['a', 'A'], ignore_case=True), ['a'])
