import unittest

from tally import sensors
from tally import routes
from tally import orders
from tally import archive


class Hidden(unittest.TestCase):
    def test_sensors_chunk(self):
        self.assertEqual(sensors.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(sensors.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(sensors.chunk([], 3), [])
        self.assertEqual(sensors.chunk(['a'], 1), [['a']])
        self.assertEqual(sensors.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            sensors.chunk([1, 2], 0)

    def test_sensors_moving_average(self):
        self.assertEqual(sensors.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(sensors.moving_average([5], 1), [5.0])
        self.assertEqual(sensors.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(sensors.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            sensors.moving_average([1, 2], 0)

    def test_sensors_invert(self):
        self.assertEqual(sensors.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(sensors.invert({}), {})
        self.assertEqual(sensors.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(sensors.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_routes_median(self):
        self.assertEqual(routes.median([3, 1, 2]), 2)
        self.assertEqual(routes.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(routes.median([5]), 5)
        self.assertEqual(routes.median([1, 2]), 1.5)
        self.assertEqual(routes.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            routes.median([])

    def test_routes_bucket(self):
        self.assertEqual(routes.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(routes.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(routes.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(routes.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(routes.bucket(7, []), 0)

    def test_routes_weighted_mean(self):
        self.assertEqual(routes.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(routes.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(routes.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            routes.weighted_mean([5, 5], [0, 0])
        self.assertEqual(routes.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_orders_snake_case(self):
        self.assertEqual(orders.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(orders.snake_case('plain'), 'plain')
        self.assertEqual(orders.snake_case('A'), 'a')
        self.assertEqual(orders.snake_case('ShipToCity'), 'ship_to_city')

    def test_orders_is_leap(self):
        self.assertEqual(orders.is_leap(2024), True)
        self.assertEqual(orders.is_leap(1900), False)
        self.assertEqual(orders.is_leap(2000), True)
        self.assertEqual(orders.is_leap(2023), False)
        self.assertEqual(orders.is_leap(2400), True)
        self.assertEqual(orders.is_leap(2100), False)

    def test_archive_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])
        self.assertEqual(archive.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(archive.rle('zz'), [('z', 2)])

    def test_archive_top_n(self):
        self.assertEqual(archive.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(archive.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(archive.top_n({}, 2), [])
        self.assertEqual(archive.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_archive_format_cents(self):
        self.assertEqual(archive.format_cents(0), '$0.00')
        self.assertEqual(archive.format_cents(123456), '$1,234.56')
        self.assertEqual(archive.format_cents(-105), '-$1.05')
        self.assertEqual(archive.format_cents(5), '$0.05')
        self.assertEqual(archive.format_cents(100000000), '$1,000,000.00')

    def test_feature(self):
        self.assertEqual(archive.top_n({'tea': 3, 'milk': 1, 'jam': 2}, 5, min_count=2), ['tea', 'jam'])
