import unittest

from wharf import timesheet
from wharf import archive
from wharf import payroll
from wharf import pricing


class Hidden(unittest.TestCase):
    def test_timesheet_merge_ranges(self):
        self.assertEqual(timesheet.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(timesheet.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(timesheet.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(timesheet.merge_ranges([]), [])
        self.assertEqual(timesheet.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_timesheet_format_cents(self):
        self.assertEqual(timesheet.format_cents(0), '$0.00')
        self.assertEqual(timesheet.format_cents(123456), '$1,234.56')
        self.assertEqual(timesheet.format_cents(-105), '-$1.05')
        self.assertEqual(timesheet.format_cents(5), '$0.05')
        self.assertEqual(timesheet.format_cents(100000000), '$1,000,000.00')

    def test_archive_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])
        self.assertEqual(archive.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(archive.rle('zz'), [('z', 2)])

    def test_archive_clamp(self):
        self.assertEqual(archive.clamp(5, 0, 10), 5)
        self.assertEqual(archive.clamp(-3, 0, 10), 0)
        self.assertEqual(archive.clamp(15, 0, 10), 10)
        self.assertEqual(archive.clamp(10, 0, 10), 10)
        self.assertEqual(archive.clamp(0, 0, 10), 0)
        self.assertEqual(archive.clamp(7, 7, 7), 7)
        self.assertEqual(archive.clamp(-20, -30, -10), -20)

    def test_archive_dedupe(self):
        self.assertEqual(archive.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(archive.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(archive.dedupe([]), [])
        self.assertEqual(archive.dedupe([1, 1, 1]), [1])

    def test_payroll_luhn_valid(self):
        self.assertEqual(payroll.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(payroll.luhn_valid('79927398713'), True)
        self.assertEqual(payroll.luhn_valid('79927398710'), False)
        self.assertEqual(payroll.luhn_valid(''), False)
        self.assertEqual(payroll.luhn_valid('059'), True)

    def test_payroll_running_total(self):
        self.assertEqual(payroll.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(payroll.running_total([]), [])
        self.assertEqual(payroll.running_total([5]), [5])
        self.assertEqual(payroll.running_total([2, -2, 2]), [2, 0, 2])

    def test_payroll_paginate(self):
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(payroll.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            payroll.paginate([1, 2], 0, 2)

    def test_pricing_word_count(self):
        self.assertEqual(pricing.word_count('a b'), 2)
        self.assertEqual(pricing.word_count('  tea  and   milk '), 3)
        self.assertEqual(pricing.word_count(''), 0)
        self.assertEqual(pricing.word_count('one'), 1)

    def test_pricing_snake_case(self):
        self.assertEqual(pricing.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(pricing.snake_case('plain'), 'plain')
        self.assertEqual(pricing.snake_case('A'), 'a')
        self.assertEqual(pricing.snake_case('ShipToCity'), 'ship_to_city')

    def test_pricing_weighted_mean(self):
        self.assertEqual(pricing.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(pricing.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(pricing.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            pricing.weighted_mean([5, 5], [0, 0])
        self.assertEqual(pricing.weighted_mean([1, 2], [0.5, 1.5]), 1.75)
