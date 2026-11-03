import unittest

from lantern import kitchen
from lantern import ledger
from lantern import sensors
from lantern import weather


class Hidden(unittest.TestCase):
    def test_kitchen_top_n(self):
        self.assertEqual(kitchen.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(kitchen.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(kitchen.top_n({}, 2), [])
        self.assertEqual(kitchen.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_kitchen_grade(self):
        self.assertEqual(kitchen.grade(95), 'A')
        self.assertEqual(kitchen.grade(90), 'A')
        self.assertEqual(kitchen.grade(85), 'B')
        self.assertEqual(kitchen.grade(80), 'B')
        self.assertEqual(kitchen.grade(61), 'D')
        self.assertEqual(kitchen.grade(59), 'F')
        self.assertEqual(kitchen.grade(0), 'F')

    def test_kitchen_rle(self):
        self.assertEqual(kitchen.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(kitchen.rle(''), [])
        self.assertEqual(kitchen.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(kitchen.rle('zz'), [('z', 2)])

    def test_ledger_truncate_words(self):
        self.assertEqual(ledger.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(ledger.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(ledger.truncate_words('', 3), '')
        self.assertEqual(ledger.truncate_words('one two three', 1), 'one...')

    def test_ledger_weighted_mean(self):
        self.assertEqual(ledger.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(ledger.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(ledger.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            ledger.weighted_mean([5, 5], [0, 0])
        self.assertEqual(ledger.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_ledger_merge_ranges(self):
        self.assertEqual(ledger.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(ledger.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(ledger.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(ledger.merge_ranges([]), [])
        self.assertEqual(ledger.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_sensors_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
        self.assertEqual(sensors.percent_change(80, 80), 0.0)
        self.assertEqual(sensors.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            sensors.percent_change(0, 5)
        self.assertEqual(sensors.percent_change(-10, -5), -50.0)

    def test_sensors_bucket(self):
        self.assertEqual(sensors.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(sensors.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(sensors.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(sensors.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(sensors.bucket(7, []), 0)

    def test_weather_chunk(self):
        self.assertEqual(weather.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(weather.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(weather.chunk([], 3), [])
        self.assertEqual(weather.chunk(['a'], 1), [['a']])
        self.assertEqual(weather.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            weather.chunk([1, 2], 0)

    def test_weather_snake_case(self):
        self.assertEqual(weather.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(weather.snake_case('plain'), 'plain')
        self.assertEqual(weather.snake_case('A'), 'a')
        self.assertEqual(weather.snake_case('ShipToCity'), 'ship_to_city')

    def test_weather_running_total(self):
        self.assertEqual(weather.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(weather.running_total([]), [])
        self.assertEqual(weather.running_total([5]), [5])
        self.assertEqual(weather.running_total([2, -2, 2]), [2, 0, 2])

    def test_feature(self):
        self.assertEqual(ledger.truncate_words('the quick brown fox', 1, ellipsis=' [more]'), 'the [more]')
