import unittest

from foundry import weather
from foundry import shipping
from foundry import tickets
from foundry import timesheet
from foundry import fleet


class Hidden(unittest.TestCase):
    def test_weather_bucket(self):
        self.assertEqual(weather.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(weather.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(weather.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(weather.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(weather.bucket(7, []), 0)

    def test_weather_top_n(self):
        self.assertEqual(weather.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(weather.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(weather.top_n({}, 2), [])
        self.assertEqual(weather.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_shipping_moving_average(self):
        self.assertEqual(shipping.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(shipping.moving_average([5], 1), [5.0])
        self.assertEqual(shipping.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(shipping.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            shipping.moving_average([1, 2], 0)

    def test_shipping_paginate(self):
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(shipping.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(shipping.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            shipping.paginate([1, 2], 0, 2)

    def test_shipping_grade(self):
        self.assertEqual(shipping.grade(95), 'A')
        self.assertEqual(shipping.grade(90), 'A')
        self.assertEqual(shipping.grade(85), 'B')
        self.assertEqual(shipping.grade(80), 'B')
        self.assertEqual(shipping.grade(61), 'D')
        self.assertEqual(shipping.grade(59), 'F')
        self.assertEqual(shipping.grade(0), 'F')

    def test_tickets_is_leap(self):
        self.assertEqual(tickets.is_leap(2024), True)
        self.assertEqual(tickets.is_leap(1900), False)
        self.assertEqual(tickets.is_leap(2000), True)
        self.assertEqual(tickets.is_leap(2023), False)
        self.assertEqual(tickets.is_leap(2400), True)
        self.assertEqual(tickets.is_leap(2100), False)

    def test_tickets_merge_ranges(self):
        self.assertEqual(tickets.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(tickets.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(tickets.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(tickets.merge_ranges([]), [])
        self.assertEqual(tickets.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_tickets_clamp(self):
        self.assertEqual(tickets.clamp(5, 0, 10), 5)
        self.assertEqual(tickets.clamp(-3, 0, 10), 0)
        self.assertEqual(tickets.clamp(15, 0, 10), 10)
        self.assertEqual(tickets.clamp(10, 0, 10), 10)
        self.assertEqual(tickets.clamp(0, 0, 10), 0)
        self.assertEqual(tickets.clamp(7, 7, 7), 7)
        self.assertEqual(tickets.clamp(-20, -30, -10), -20)

    def test_timesheet_median(self):
        self.assertEqual(timesheet.median([3, 1, 2]), 2)
        self.assertEqual(timesheet.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(timesheet.median([5]), 5)
        self.assertEqual(timesheet.median([1, 2]), 1.5)
        self.assertEqual(timesheet.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            timesheet.median([])

    def test_timesheet_truncate_words(self):
        self.assertEqual(timesheet.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(timesheet.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(timesheet.truncate_words('', 3), '')
        self.assertEqual(timesheet.truncate_words('one two three', 1), 'one...')

    def test_timesheet_chunk(self):
        self.assertEqual(timesheet.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(timesheet.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(timesheet.chunk([], 3), [])
        self.assertEqual(timesheet.chunk(['a'], 1), [['a']])
        self.assertEqual(timesheet.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            timesheet.chunk([1, 2], 0)

    def test_fleet_luhn_valid(self):
        self.assertEqual(fleet.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(fleet.luhn_valid('79927398713'), True)
        self.assertEqual(fleet.luhn_valid('79927398710'), False)
        self.assertEqual(fleet.luhn_valid(''), False)
        self.assertEqual(fleet.luhn_valid('059'), True)

    def test_fleet_running_total(self):
        self.assertEqual(fleet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(fleet.running_total([]), [])
        self.assertEqual(fleet.running_total([5]), [5])
        self.assertEqual(fleet.running_total([2, -2, 2]), [2, 0, 2])
