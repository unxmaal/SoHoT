import unittest

from harbor import tickets
from harbor import timesheet
from harbor import pricing
from harbor import weather


class Hidden(unittest.TestCase):
    def test_tickets_moving_average(self):
        self.assertEqual(tickets.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(tickets.moving_average([5], 1), [5.0])
        self.assertEqual(tickets.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(tickets.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            tickets.moving_average([1, 2], 0)

    def test_tickets_luhn_valid(self):
        self.assertEqual(tickets.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(tickets.luhn_valid('79927398713'), True)
        self.assertEqual(tickets.luhn_valid('79927398710'), False)
        self.assertEqual(tickets.luhn_valid(''), False)
        self.assertEqual(tickets.luhn_valid('059'), True)

    def test_tickets_word_count(self):
        self.assertEqual(tickets.word_count('a b'), 2)
        self.assertEqual(tickets.word_count('  tea  and   milk '), 3)
        self.assertEqual(tickets.word_count(''), 0)
        self.assertEqual(tickets.word_count('one'), 1)

    def test_timesheet_paginate(self):
        self.assertEqual(timesheet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(timesheet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(timesheet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(timesheet.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            timesheet.paginate([1, 2], 0, 2)

    def test_timesheet_running_total(self):
        self.assertEqual(timesheet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(timesheet.running_total([]), [])
        self.assertEqual(timesheet.running_total([5]), [5])
        self.assertEqual(timesheet.running_total([2, -2, 2]), [2, 0, 2])

    def test_pricing_percent_change(self):
        self.assertEqual(pricing.percent_change(50, 75), 50.0)
        self.assertEqual(pricing.percent_change(200, 150), -25.0)
        self.assertEqual(pricing.percent_change(80, 80), 0.0)
        self.assertEqual(pricing.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            pricing.percent_change(0, 5)
        self.assertEqual(pricing.percent_change(-10, -5), -50.0)

    def test_pricing_median(self):
        self.assertEqual(pricing.median([3, 1, 2]), 2)
        self.assertEqual(pricing.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(pricing.median([5]), 5)
        self.assertEqual(pricing.median([1, 2]), 1.5)
        self.assertEqual(pricing.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            pricing.median([])

    def test_weather_parse_duration(self):
        self.assertEqual(weather.parse_duration('1h30m'), 5400)
        self.assertEqual(weather.parse_duration('45s'), 45)
        self.assertEqual(weather.parse_duration('2h'), 7200)
        self.assertEqual(weather.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            weather.parse_duration('')
        with self.assertRaises(ValueError):
            weather.parse_duration('5x')
        self.assertEqual(weather.parse_duration('10m5s'), 605)

    def test_weather_truncate_words(self):
        self.assertEqual(weather.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(weather.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(weather.truncate_words('', 3), '')
        self.assertEqual(weather.truncate_words('one two three', 1), 'one...')

    def test_weather_merge_ranges(self):
        self.assertEqual(weather.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(weather.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(weather.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(weather.merge_ranges([]), [])
        self.assertEqual(weather.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])
