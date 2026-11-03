import unittest

from kiln import kitchen
from kiln import archive
from kiln import sensors
from kiln import survey


class Hidden(unittest.TestCase):
    def test_kitchen_moving_average(self):
        self.assertEqual(kitchen.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(kitchen.moving_average([5], 1), [5.0])
        self.assertEqual(kitchen.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(kitchen.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            kitchen.moving_average([1, 2], 0)

    def test_kitchen_percent_change(self):
        self.assertEqual(kitchen.percent_change(50, 75), 50.0)
        self.assertEqual(kitchen.percent_change(200, 150), -25.0)
        self.assertEqual(kitchen.percent_change(80, 80), 0.0)
        self.assertEqual(kitchen.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            kitchen.percent_change(0, 5)
        self.assertEqual(kitchen.percent_change(-10, -5), -50.0)

    def test_kitchen_truncate_words(self):
        self.assertEqual(kitchen.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(kitchen.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(kitchen.truncate_words('', 3), '')
        self.assertEqual(kitchen.truncate_words('one two three', 1), 'one...')

    def test_archive_clamp(self):
        self.assertEqual(archive.clamp(5, 0, 10), 5)
        self.assertEqual(archive.clamp(-3, 0, 10), 0)
        self.assertEqual(archive.clamp(15, 0, 10), 10)
        self.assertEqual(archive.clamp(10, 0, 10), 10)
        self.assertEqual(archive.clamp(0, 0, 10), 0)
        self.assertEqual(archive.clamp(7, 7, 7), 7)
        self.assertEqual(archive.clamp(-20, -30, -10), -20)

    def test_archive_parse_duration(self):
        self.assertEqual(archive.parse_duration('1h30m'), 5400)
        self.assertEqual(archive.parse_duration('45s'), 45)
        self.assertEqual(archive.parse_duration('2h'), 7200)
        self.assertEqual(archive.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            archive.parse_duration('')
        with self.assertRaises(ValueError):
            archive.parse_duration('5x')
        self.assertEqual(archive.parse_duration('10m5s'), 605)

    def test_archive_weighted_mean(self):
        self.assertEqual(archive.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(archive.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(archive.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            archive.weighted_mean([5, 5], [0, 0])
        self.assertEqual(archive.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_sensors_invert(self):
        self.assertEqual(sensors.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(sensors.invert({}), {})
        self.assertEqual(sensors.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(sensors.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_sensors_grade(self):
        self.assertEqual(sensors.grade(95), 'A')
        self.assertEqual(sensors.grade(90), 'A')
        self.assertEqual(sensors.grade(85), 'B')
        self.assertEqual(sensors.grade(80), 'B')
        self.assertEqual(sensors.grade(61), 'D')
        self.assertEqual(sensors.grade(59), 'F')
        self.assertEqual(sensors.grade(0), 'F')

    def test_sensors_paginate(self):
        self.assertEqual(sensors.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(sensors.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(sensors.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(sensors.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            sensors.paginate([1, 2], 0, 2)

    def test_survey_luhn_valid(self):
        self.assertEqual(survey.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(survey.luhn_valid('79927398713'), True)
        self.assertEqual(survey.luhn_valid('79927398710'), False)
        self.assertEqual(survey.luhn_valid(''), False)
        self.assertEqual(survey.luhn_valid('059'), True)

    def test_survey_bucket(self):
        self.assertEqual(survey.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(survey.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(survey.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(survey.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(survey.bucket(7, []), 0)
