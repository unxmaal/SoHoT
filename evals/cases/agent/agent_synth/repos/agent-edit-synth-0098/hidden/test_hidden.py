import unittest

from quarry import sensors
from quarry import ledger
from quarry import survey
from quarry import routes


class Hidden(unittest.TestCase):
    def test_sensors_grade(self):
        self.assertEqual(sensors.grade(95), 'A')
        self.assertEqual(sensors.grade(90), 'A')
        self.assertEqual(sensors.grade(85), 'B')
        self.assertEqual(sensors.grade(80), 'B')
        self.assertEqual(sensors.grade(61), 'D')
        self.assertEqual(sensors.grade(59), 'F')
        self.assertEqual(sensors.grade(0), 'F')

    def test_sensors_invert(self):
        self.assertEqual(sensors.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(sensors.invert({}), {})
        self.assertEqual(sensors.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(sensors.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_ledger_running_total(self):
        self.assertEqual(ledger.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(ledger.running_total([]), [])
        self.assertEqual(ledger.running_total([5]), [5])
        self.assertEqual(ledger.running_total([2, -2, 2]), [2, 0, 2])

    def test_ledger_clamp(self):
        self.assertEqual(ledger.clamp(5, 0, 10), 5)
        self.assertEqual(ledger.clamp(-3, 0, 10), 0)
        self.assertEqual(ledger.clamp(15, 0, 10), 10)
        self.assertEqual(ledger.clamp(10, 0, 10), 10)
        self.assertEqual(ledger.clamp(0, 0, 10), 0)
        self.assertEqual(ledger.clamp(7, 7, 7), 7)
        self.assertEqual(ledger.clamp(-20, -30, -10), -20)

    def test_survey_rle(self):
        self.assertEqual(survey.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(survey.rle(''), [])
        self.assertEqual(survey.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(survey.rle('zz'), [('z', 2)])

    def test_survey_percent_change(self):
        self.assertEqual(survey.percent_change(50, 75), 50.0)
        self.assertEqual(survey.percent_change(200, 150), -25.0)
        self.assertEqual(survey.percent_change(80, 80), 0.0)
        self.assertEqual(survey.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            survey.percent_change(0, 5)
        self.assertEqual(survey.percent_change(-10, -5), -50.0)

    def test_routes_is_leap(self):
        self.assertEqual(routes.is_leap(2024), True)
        self.assertEqual(routes.is_leap(1900), False)
        self.assertEqual(routes.is_leap(2000), True)
        self.assertEqual(routes.is_leap(2023), False)
        self.assertEqual(routes.is_leap(2400), True)
        self.assertEqual(routes.is_leap(2100), False)

    def test_routes_truncate_words(self):
        self.assertEqual(routes.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(routes.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(routes.truncate_words('', 3), '')
        self.assertEqual(routes.truncate_words('one two three', 1), 'one...')

    def test_feature(self):
        with self.assertRaises(ValueError):
            ledger.clamp(5, 10, 0)
        with self.assertRaises(ValueError):
            ledger.clamp(1, 3, 2)
