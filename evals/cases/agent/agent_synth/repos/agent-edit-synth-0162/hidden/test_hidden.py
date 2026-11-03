import unittest

from depot import orders
from depot import kitchen
from depot import weather
from depot import metrics


class Hidden(unittest.TestCase):
    def test_orders_invert(self):
        self.assertEqual(orders.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(orders.invert({}), {})
        self.assertEqual(orders.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(orders.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_orders_is_leap(self):
        self.assertEqual(orders.is_leap(2024), True)
        self.assertEqual(orders.is_leap(1900), False)
        self.assertEqual(orders.is_leap(2000), True)
        self.assertEqual(orders.is_leap(2023), False)
        self.assertEqual(orders.is_leap(2400), True)
        self.assertEqual(orders.is_leap(2100), False)

    def test_orders_parse_duration(self):
        self.assertEqual(orders.parse_duration('1h30m'), 5400)
        self.assertEqual(orders.parse_duration('45s'), 45)
        self.assertEqual(orders.parse_duration('2h'), 7200)
        self.assertEqual(orders.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            orders.parse_duration('')
        with self.assertRaises(ValueError):
            orders.parse_duration('5x')
        self.assertEqual(orders.parse_duration('10m5s'), 605)

    def test_kitchen_chunk(self):
        self.assertEqual(kitchen.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(kitchen.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(kitchen.chunk([], 3), [])
        self.assertEqual(kitchen.chunk(['a'], 1), [['a']])
        self.assertEqual(kitchen.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            kitchen.chunk([1, 2], 0)

    def test_kitchen_format_cents(self):
        self.assertEqual(kitchen.format_cents(0), '$0.00')
        self.assertEqual(kitchen.format_cents(123456), '$1,234.56')
        self.assertEqual(kitchen.format_cents(-105), '-$1.05')
        self.assertEqual(kitchen.format_cents(5), '$0.05')
        self.assertEqual(kitchen.format_cents(100000000), '$1,000,000.00')

    def test_weather_rle(self):
        self.assertEqual(weather.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(weather.rle(''), [])
        self.assertEqual(weather.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(weather.rle('zz'), [('z', 2)])

    def test_weather_top_n(self):
        self.assertEqual(weather.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(weather.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(weather.top_n({}, 2), [])
        self.assertEqual(weather.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_metrics_clamp(self):
        self.assertEqual(metrics.clamp(5, 0, 10), 5)
        self.assertEqual(metrics.clamp(-3, 0, 10), 0)
        self.assertEqual(metrics.clamp(15, 0, 10), 10)
        self.assertEqual(metrics.clamp(10, 0, 10), 10)
        self.assertEqual(metrics.clamp(0, 0, 10), 0)
        self.assertEqual(metrics.clamp(7, 7, 7), 7)
        self.assertEqual(metrics.clamp(-20, -30, -10), -20)

    def test_metrics_median(self):
        self.assertEqual(metrics.median([3, 1, 2]), 2)
        self.assertEqual(metrics.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(metrics.median([5]), 5)
        self.assertEqual(metrics.median([1, 2]), 1.5)
        self.assertEqual(metrics.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            metrics.median([])

    def test_feature(self):
        self.assertEqual(metrics.median([], default=0), 0)
        self.assertEqual(metrics.median([], default=-1), -1)
        self.assertEqual(metrics.median([1, 3], default=0), 2.0)
