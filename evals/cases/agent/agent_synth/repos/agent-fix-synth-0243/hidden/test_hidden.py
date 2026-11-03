import unittest

from mill import tickets
from mill import payroll
from mill import weather


class Hidden(unittest.TestCase):
    def test_tickets_moving_average(self):
        self.assertEqual(tickets.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(tickets.moving_average([5], 1), [5.0])
        self.assertEqual(tickets.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(tickets.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            tickets.moving_average([1, 2], 0)

    def test_tickets_weighted_mean(self):
        self.assertEqual(tickets.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(tickets.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(tickets.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            tickets.weighted_mean([5, 5], [0, 0])
        self.assertEqual(tickets.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_payroll_paginate(self):
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(payroll.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            payroll.paginate([1, 2], 0, 2)

    def test_payroll_percent_change(self):
        self.assertEqual(payroll.percent_change(50, 75), 50.0)
        self.assertEqual(payroll.percent_change(200, 150), -25.0)
        self.assertEqual(payroll.percent_change(80, 80), 0.0)
        self.assertEqual(payroll.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            payroll.percent_change(0, 5)
        self.assertEqual(payroll.percent_change(-10, -5), -50.0)

    def test_weather_dedupe(self):
        self.assertEqual(weather.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(weather.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(weather.dedupe([]), [])
        self.assertEqual(weather.dedupe([1, 1, 1]), [1])

    def test_weather_rle(self):
        self.assertEqual(weather.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(weather.rle(''), [])
        self.assertEqual(weather.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(weather.rle('zz'), [('z', 2)])

    def test_weather_is_leap(self):
        self.assertEqual(weather.is_leap(2024), True)
        self.assertEqual(weather.is_leap(1900), False)
        self.assertEqual(weather.is_leap(2000), True)
        self.assertEqual(weather.is_leap(2023), False)
        self.assertEqual(weather.is_leap(2400), True)
        self.assertEqual(weather.is_leap(2100), False)
