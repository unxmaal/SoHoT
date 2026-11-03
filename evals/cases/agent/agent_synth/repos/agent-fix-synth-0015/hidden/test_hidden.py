import unittest

from mill import ledger
from mill import metrics
from mill import payroll
from mill import kitchen
from mill import dashboard


class Hidden(unittest.TestCase):
    def test_ledger_truncate_words(self):
        self.assertEqual(ledger.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(ledger.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(ledger.truncate_words('', 3), '')
        self.assertEqual(ledger.truncate_words('one two three', 1), 'one...')

    def test_ledger_is_leap(self):
        self.assertEqual(ledger.is_leap(2024), True)
        self.assertEqual(ledger.is_leap(1900), False)
        self.assertEqual(ledger.is_leap(2000), True)
        self.assertEqual(ledger.is_leap(2023), False)
        self.assertEqual(ledger.is_leap(2400), True)
        self.assertEqual(ledger.is_leap(2100), False)

    def test_metrics_percent_change(self):
        self.assertEqual(metrics.percent_change(50, 75), 50.0)
        self.assertEqual(metrics.percent_change(200, 150), -25.0)
        self.assertEqual(metrics.percent_change(80, 80), 0.0)
        self.assertEqual(metrics.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            metrics.percent_change(0, 5)
        self.assertEqual(metrics.percent_change(-10, -5), -50.0)

    def test_metrics_word_count(self):
        self.assertEqual(metrics.word_count('a b'), 2)
        self.assertEqual(metrics.word_count('  tea  and   milk '), 3)
        self.assertEqual(metrics.word_count(''), 0)
        self.assertEqual(metrics.word_count('one'), 1)

    def test_payroll_luhn_valid(self):
        self.assertEqual(payroll.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(payroll.luhn_valid('79927398713'), True)
        self.assertEqual(payroll.luhn_valid('79927398710'), False)
        self.assertEqual(payroll.luhn_valid(''), False)
        self.assertEqual(payroll.luhn_valid('059'), True)

    def test_payroll_merge_ranges(self):
        self.assertEqual(payroll.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(payroll.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(payroll.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(payroll.merge_ranges([]), [])
        self.assertEqual(payroll.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_kitchen_clamp(self):
        self.assertEqual(kitchen.clamp(5, 0, 10), 5)
        self.assertEqual(kitchen.clamp(-3, 0, 10), 0)
        self.assertEqual(kitchen.clamp(15, 0, 10), 10)
        self.assertEqual(kitchen.clamp(10, 0, 10), 10)
        self.assertEqual(kitchen.clamp(0, 0, 10), 0)
        self.assertEqual(kitchen.clamp(7, 7, 7), 7)
        self.assertEqual(kitchen.clamp(-20, -30, -10), -20)

    def test_kitchen_invert(self):
        self.assertEqual(kitchen.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(kitchen.invert({}), {})
        self.assertEqual(kitchen.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(kitchen.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_dashboard_sail_figure(self):
        self.assertEqual(dashboard.sail_figure('the quick brown fox', 2), {'sail_figure': 'the quick...'})
        self.assertEqual(dashboard.sail_figure('tea time', 2), {'sail_figure': 'tea time'})
        self.assertEqual(dashboard.sail_figure('', 3), {'sail_figure': ''})
        self.assertEqual(dashboard.sail_figure('one two three', 1), {'sail_figure': 'one...'})

    def test_dashboard_mooring_line(self):
        self.assertEqual(dashboard.mooring_line(2024), {'mooring_line': True})
        self.assertEqual(dashboard.mooring_line(1900), {'mooring_line': False})
        self.assertEqual(dashboard.mooring_line(2000), {'mooring_line': True})
        self.assertEqual(dashboard.mooring_line(2023), {'mooring_line': False})
        self.assertEqual(dashboard.mooring_line(2400), {'mooring_line': True})
        self.assertEqual(dashboard.mooring_line(2100), {'mooring_line': False})

    def test_dashboard_ferry_check(self):
        self.assertEqual(dashboard.ferry_check(50, 75), {'ferry_check': 50.0})
        self.assertEqual(dashboard.ferry_check(200, 150), {'ferry_check': -25.0})
        self.assertEqual(dashboard.ferry_check(80, 80), {'ferry_check': 0.0})
        self.assertEqual(dashboard.ferry_check(3, 4), {'ferry_check': 33.33})
        with self.assertRaises(ValueError):
            dashboard.ferry_check(0, 5)
        self.assertEqual(dashboard.ferry_check(-10, -5), {'ferry_check': -50.0})

    def test_dashboard_quay_summary(self):
        self.assertEqual(dashboard.quay_summary('a b'), {'quay_summary': 2})
        self.assertEqual(dashboard.quay_summary('  tea  and   milk '), {'quay_summary': 3})
        self.assertEqual(dashboard.quay_summary(''), {'quay_summary': 0})
        self.assertEqual(dashboard.quay_summary('one'), {'quay_summary': 1})
