import unittest

from granary import ledger
from granary import shipping
from granary import payroll
from granary import survey


class Hidden(unittest.TestCase):
    def test_ledger_format_cents(self):
        self.assertEqual(ledger.format_cents(0), '$0.00')
        self.assertEqual(ledger.format_cents(123456), '$1,234.56')
        self.assertEqual(ledger.format_cents(-105), '-$1.05')
        self.assertEqual(ledger.format_cents(5), '$0.05')
        self.assertEqual(ledger.format_cents(100000000), '$1,000,000.00')

    def test_ledger_bucket(self):
        self.assertEqual(ledger.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(ledger.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(ledger.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(ledger.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(ledger.bucket(7, []), 0)

    def test_shipping_is_leap(self):
        self.assertEqual(shipping.is_leap(2024), True)
        self.assertEqual(shipping.is_leap(1900), False)
        self.assertEqual(shipping.is_leap(2000), True)
        self.assertEqual(shipping.is_leap(2023), False)
        self.assertEqual(shipping.is_leap(2400), True)
        self.assertEqual(shipping.is_leap(2100), False)

    def test_shipping_word_count(self):
        self.assertEqual(shipping.word_count('a b'), 2)
        self.assertEqual(shipping.word_count('  tea  and   milk '), 3)
        self.assertEqual(shipping.word_count(''), 0)
        self.assertEqual(shipping.word_count('one'), 1)

    def test_payroll_weighted_mean(self):
        self.assertEqual(payroll.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(payroll.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(payroll.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            payroll.weighted_mean([5, 5], [0, 0])
        self.assertEqual(payroll.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_payroll_invert(self):
        self.assertEqual(payroll.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(payroll.invert({}), {})
        self.assertEqual(payroll.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(payroll.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_payroll_top_n(self):
        self.assertEqual(payroll.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(payroll.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(payroll.top_n({}, 2), [])
        self.assertEqual(payroll.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_survey_percent_change(self):
        self.assertEqual(survey.percent_change(50, 75), 50.0)
        self.assertEqual(survey.percent_change(200, 150), -25.0)
        self.assertEqual(survey.percent_change(80, 80), 0.0)
        self.assertEqual(survey.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            survey.percent_change(0, 5)
        self.assertEqual(survey.percent_change(-10, -5), -50.0)

    def test_survey_dedupe(self):
        self.assertEqual(survey.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(survey.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(survey.dedupe([]), [])
        self.assertEqual(survey.dedupe([1, 1, 1]), [1])
