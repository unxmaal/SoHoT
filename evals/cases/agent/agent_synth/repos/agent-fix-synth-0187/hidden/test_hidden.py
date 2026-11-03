import unittest

from granary import payroll
from granary import billing
from granary import survey


class Hidden(unittest.TestCase):
    def test_payroll_grade(self):
        self.assertEqual(payroll.grade(95), 'A')
        self.assertEqual(payroll.grade(90), 'A')
        self.assertEqual(payroll.grade(85), 'B')
        self.assertEqual(payroll.grade(80), 'B')
        self.assertEqual(payroll.grade(61), 'D')
        self.assertEqual(payroll.grade(59), 'F')
        self.assertEqual(payroll.grade(0), 'F')

    def test_payroll_chunk(self):
        self.assertEqual(payroll.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(payroll.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(payroll.chunk([], 3), [])
        self.assertEqual(payroll.chunk(['a'], 1), [['a']])
        self.assertEqual(payroll.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            payroll.chunk([1, 2], 0)

    def test_payroll_luhn_valid(self):
        self.assertEqual(payroll.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(payroll.luhn_valid('79927398713'), True)
        self.assertEqual(payroll.luhn_valid('79927398710'), False)
        self.assertEqual(payroll.luhn_valid(''), False)
        self.assertEqual(payroll.luhn_valid('059'), True)

    def test_billing_format_cents(self):
        self.assertEqual(billing.format_cents(0), '$0.00')
        self.assertEqual(billing.format_cents(123456), '$1,234.56')
        self.assertEqual(billing.format_cents(-105), '-$1.05')
        self.assertEqual(billing.format_cents(5), '$0.05')
        self.assertEqual(billing.format_cents(100000000), '$1,000,000.00')

    def test_billing_word_count(self):
        self.assertEqual(billing.word_count('a b'), 2)
        self.assertEqual(billing.word_count('  tea  and   milk '), 3)
        self.assertEqual(billing.word_count(''), 0)
        self.assertEqual(billing.word_count('one'), 1)

    def test_survey_merge_ranges(self):
        self.assertEqual(survey.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(survey.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(survey.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(survey.merge_ranges([]), [])
        self.assertEqual(survey.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_survey_clamp(self):
        self.assertEqual(survey.clamp(5, 0, 10), 5)
        self.assertEqual(survey.clamp(-3, 0, 10), 0)
        self.assertEqual(survey.clamp(15, 0, 10), 10)
        self.assertEqual(survey.clamp(10, 0, 10), 10)
        self.assertEqual(survey.clamp(0, 0, 10), 0)
        self.assertEqual(survey.clamp(7, 7, 7), 7)
        self.assertEqual(survey.clamp(-20, -30, -10), -20)

    def test_survey_running_total(self):
        self.assertEqual(survey.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(survey.running_total([]), [])
        self.assertEqual(survey.running_total([5]), [5])
        self.assertEqual(survey.running_total([2, -2, 2]), [2, 0, 2])
