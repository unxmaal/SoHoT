import unittest

from harbor import tickets
from harbor import budget
from harbor import metrics
from harbor import weather


class Hidden(unittest.TestCase):
    def test_tickets_paginate(self):
        self.assertEqual(tickets.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(tickets.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(tickets.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(tickets.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            tickets.paginate([1, 2], 0, 2)

    def test_tickets_weighted_mean(self):
        self.assertEqual(tickets.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(tickets.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(tickets.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            tickets.weighted_mean([5, 5], [0, 0])
        self.assertEqual(tickets.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_budget_invert(self):
        self.assertEqual(budget.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(budget.invert({}), {})
        self.assertEqual(budget.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(budget.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_budget_grade(self):
        self.assertEqual(budget.grade(95), 'A')
        self.assertEqual(budget.grade(90), 'A')
        self.assertEqual(budget.grade(85), 'B')
        self.assertEqual(budget.grade(80), 'B')
        self.assertEqual(budget.grade(61), 'D')
        self.assertEqual(budget.grade(59), 'F')
        self.assertEqual(budget.grade(0), 'F')

    def test_budget_median(self):
        self.assertEqual(budget.median([3, 1, 2]), 2)
        self.assertEqual(budget.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(budget.median([5]), 5)
        self.assertEqual(budget.median([1, 2]), 1.5)
        self.assertEqual(budget.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            budget.median([])

    def test_metrics_truncate_words(self):
        self.assertEqual(metrics.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(metrics.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(metrics.truncate_words('', 3), '')
        self.assertEqual(metrics.truncate_words('one two three', 1), 'one...')

    def test_metrics_dedupe(self):
        self.assertEqual(metrics.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(metrics.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(metrics.dedupe([]), [])
        self.assertEqual(metrics.dedupe([1, 1, 1]), [1])

    def test_weather_percent_change(self):
        self.assertEqual(weather.percent_change(50, 75), 50.0)
        self.assertEqual(weather.percent_change(200, 150), -25.0)
        self.assertEqual(weather.percent_change(80, 80), 0.0)
        self.assertEqual(weather.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            weather.percent_change(0, 5)
        self.assertEqual(weather.percent_change(-10, -5), -50.0)

    def test_weather_is_leap(self):
        self.assertEqual(weather.is_leap(2024), True)
        self.assertEqual(weather.is_leap(1900), False)
        self.assertEqual(weather.is_leap(2000), True)
        self.assertEqual(weather.is_leap(2023), False)
        self.assertEqual(weather.is_leap(2400), True)
        self.assertEqual(weather.is_leap(2100), False)
