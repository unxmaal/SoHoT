import unittest

from harbor import sensors
from harbor import routes
from harbor import weather
from harbor import fleet
from harbor import archive


class Hidden(unittest.TestCase):
    def test_sensors_median(self):
        self.assertEqual(sensors.median([3, 1, 2]), 2)
        self.assertEqual(sensors.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(sensors.median([5]), 5)
        self.assertEqual(sensors.median([1, 2]), 1.5)
        self.assertEqual(sensors.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            sensors.median([])

    def test_sensors_parse_duration(self):
        self.assertEqual(sensors.parse_duration('1h30m'), 5400)
        self.assertEqual(sensors.parse_duration('45s'), 45)
        self.assertEqual(sensors.parse_duration('2h'), 7200)
        self.assertEqual(sensors.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            sensors.parse_duration('')
        with self.assertRaises(ValueError):
            sensors.parse_duration('5x')
        self.assertEqual(sensors.parse_duration('10m5s'), 605)

    def test_routes_format_cents(self):
        self.assertEqual(routes.format_cents(0), '$0.00')
        self.assertEqual(routes.format_cents(123456), '$1,234.56')
        self.assertEqual(routes.format_cents(-105), '-$1.05')
        self.assertEqual(routes.format_cents(5), '$0.05')
        self.assertEqual(routes.format_cents(100000000), '$1,000,000.00')

    def test_routes_grade(self):
        self.assertEqual(routes.grade(95), 'A')
        self.assertEqual(routes.grade(90), 'A')
        self.assertEqual(routes.grade(85), 'B')
        self.assertEqual(routes.grade(80), 'B')
        self.assertEqual(routes.grade(61), 'D')
        self.assertEqual(routes.grade(59), 'F')
        self.assertEqual(routes.grade(0), 'F')

    def test_routes_clamp(self):
        self.assertEqual(routes.clamp(5, 0, 10), 5)
        self.assertEqual(routes.clamp(-3, 0, 10), 0)
        self.assertEqual(routes.clamp(15, 0, 10), 10)
        self.assertEqual(routes.clamp(10, 0, 10), 10)
        self.assertEqual(routes.clamp(0, 0, 10), 0)
        self.assertEqual(routes.clamp(7, 7, 7), 7)
        self.assertEqual(routes.clamp(-20, -30, -10), -20)

    def test_weather_moving_average(self):
        self.assertEqual(weather.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(weather.moving_average([5], 1), [5.0])
        self.assertEqual(weather.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(weather.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            weather.moving_average([1, 2], 0)

    def test_weather_percent_change(self):
        self.assertEqual(weather.percent_change(50, 75), 50.0)
        self.assertEqual(weather.percent_change(200, 150), -25.0)
        self.assertEqual(weather.percent_change(80, 80), 0.0)
        self.assertEqual(weather.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            weather.percent_change(0, 5)
        self.assertEqual(weather.percent_change(-10, -5), -50.0)

    def test_weather_chunk(self):
        self.assertEqual(weather.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(weather.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(weather.chunk([], 3), [])
        self.assertEqual(weather.chunk(['a'], 1), [['a']])
        self.assertEqual(weather.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            weather.chunk([1, 2], 0)

    def test_fleet_bucket(self):
        self.assertEqual(fleet.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(fleet.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(fleet.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(fleet.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(fleet.bucket(7, []), 0)

    def test_fleet_word_count(self):
        self.assertEqual(fleet.word_count('a b'), 2)
        self.assertEqual(fleet.word_count('  tea  and   milk '), 3)
        self.assertEqual(fleet.word_count(''), 0)
        self.assertEqual(fleet.word_count('one'), 1)

    def test_archive_weighted_mean(self):
        self.assertEqual(archive.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(archive.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(archive.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            archive.weighted_mean([5, 5], [0, 0])
        self.assertEqual(archive.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_archive_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])
        self.assertEqual(archive.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(archive.rle('zz'), [('z', 2)])

    def test_archive_paginate(self):
        self.assertEqual(archive.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(archive.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(archive.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(archive.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            archive.paginate([1, 2], 0, 2)
