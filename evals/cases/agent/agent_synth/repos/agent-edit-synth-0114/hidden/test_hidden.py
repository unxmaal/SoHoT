import unittest

from orchard import timesheet
from orchard import billing
from orchard import ledger
from orchard import weather


class Hidden(unittest.TestCase):
    def test_timesheet_paginate(self):
        self.assertEqual(timesheet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(timesheet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(timesheet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(timesheet.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            timesheet.paginate([1, 2], 0, 2)

    def test_timesheet_snake_case(self):
        self.assertEqual(timesheet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(timesheet.snake_case('plain'), 'plain')
        self.assertEqual(timesheet.snake_case('A'), 'a')
        self.assertEqual(timesheet.snake_case('ShipToCity'), 'ship_to_city')

    def test_timesheet_running_total(self):
        self.assertEqual(timesheet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(timesheet.running_total([]), [])
        self.assertEqual(timesheet.running_total([5]), [5])
        self.assertEqual(timesheet.running_total([2, -2, 2]), [2, 0, 2])

    def test_billing_is_leap(self):
        self.assertEqual(billing.is_leap(2024), True)
        self.assertEqual(billing.is_leap(1900), False)
        self.assertEqual(billing.is_leap(2000), True)
        self.assertEqual(billing.is_leap(2023), False)
        self.assertEqual(billing.is_leap(2400), True)
        self.assertEqual(billing.is_leap(2100), False)

    def test_billing_format_cents(self):
        self.assertEqual(billing.format_cents(0), '$0.00')
        self.assertEqual(billing.format_cents(123456), '$1,234.56')
        self.assertEqual(billing.format_cents(-105), '-$1.05')
        self.assertEqual(billing.format_cents(5), '$0.05')
        self.assertEqual(billing.format_cents(100000000), '$1,000,000.00')

    def test_ledger_luhn_valid(self):
        self.assertEqual(ledger.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(ledger.luhn_valid('79927398713'), True)
        self.assertEqual(ledger.luhn_valid('79927398710'), False)
        self.assertEqual(ledger.luhn_valid(''), False)
        self.assertEqual(ledger.luhn_valid('059'), True)

    def test_ledger_parse_duration(self):
        self.assertEqual(ledger.parse_duration('1h30m'), 5400)
        self.assertEqual(ledger.parse_duration('45s'), 45)
        self.assertEqual(ledger.parse_duration('2h'), 7200)
        self.assertEqual(ledger.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            ledger.parse_duration('')
        with self.assertRaises(ValueError):
            ledger.parse_duration('5x')
        self.assertEqual(ledger.parse_duration('10m5s'), 605)

    def test_ledger_median(self):
        self.assertEqual(ledger.median([3, 1, 2]), 2)
        self.assertEqual(ledger.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(ledger.median([5]), 5)
        self.assertEqual(ledger.median([1, 2]), 1.5)
        self.assertEqual(ledger.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            ledger.median([])

    def test_weather_rle(self):
        self.assertEqual(weather.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(weather.rle(''), [])
        self.assertEqual(weather.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(weather.rle('zz'), [('z', 2)])

    def test_weather_merge_ranges(self):
        self.assertEqual(weather.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(weather.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(weather.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(weather.merge_ranges([]), [])
        self.assertEqual(weather.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_feature(self):
        self.assertEqual(billing.format_cents(123456, symbol='GBP '), 'GBP 1,234.56')
        self.assertEqual(billing.format_cents(-105, symbol='EUR '), '-EUR 1.05')
