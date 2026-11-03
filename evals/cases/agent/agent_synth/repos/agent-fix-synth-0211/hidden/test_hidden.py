import unittest

from kiln import ledger
from kiln import payroll
from kiln import pricing
from kiln import tickets


class Hidden(unittest.TestCase):
    def test_ledger_is_leap(self):
        self.assertEqual(ledger.is_leap(2024), True)
        self.assertEqual(ledger.is_leap(1900), False)
        self.assertEqual(ledger.is_leap(2000), True)
        self.assertEqual(ledger.is_leap(2023), False)
        self.assertEqual(ledger.is_leap(2400), True)
        self.assertEqual(ledger.is_leap(2100), False)

    def test_ledger_merge_ranges(self):
        self.assertEqual(ledger.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(ledger.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(ledger.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(ledger.merge_ranges([]), [])
        self.assertEqual(ledger.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_ledger_bucket(self):
        self.assertEqual(ledger.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(ledger.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(ledger.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(ledger.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(ledger.bucket(7, []), 0)

    def test_payroll_rle(self):
        self.assertEqual(payroll.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(payroll.rle(''), [])
        self.assertEqual(payroll.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(payroll.rle('zz'), [('z', 2)])

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

    def test_pricing_weighted_mean(self):
        self.assertEqual(pricing.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(pricing.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(pricing.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            pricing.weighted_mean([5, 5], [0, 0])
        self.assertEqual(pricing.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_pricing_grade(self):
        self.assertEqual(pricing.grade(95), 'A')
        self.assertEqual(pricing.grade(90), 'A')
        self.assertEqual(pricing.grade(85), 'B')
        self.assertEqual(pricing.grade(80), 'B')
        self.assertEqual(pricing.grade(61), 'D')
        self.assertEqual(pricing.grade(59), 'F')
        self.assertEqual(pricing.grade(0), 'F')

    def test_pricing_luhn_valid(self):
        self.assertEqual(pricing.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(pricing.luhn_valid('79927398713'), True)
        self.assertEqual(pricing.luhn_valid('79927398710'), False)
        self.assertEqual(pricing.luhn_valid(''), False)
        self.assertEqual(pricing.luhn_valid('059'), True)

    def test_tickets_format_cents(self):
        self.assertEqual(tickets.format_cents(0), '$0.00')
        self.assertEqual(tickets.format_cents(123456), '$1,234.56')
        self.assertEqual(tickets.format_cents(-105), '-$1.05')
        self.assertEqual(tickets.format_cents(5), '$0.05')
        self.assertEqual(tickets.format_cents(100000000), '$1,000,000.00')

    def test_tickets_running_total(self):
        self.assertEqual(tickets.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(tickets.running_total([]), [])
        self.assertEqual(tickets.running_total([5]), [5])
        self.assertEqual(tickets.running_total([2, -2, 2]), [2, 0, 2])
