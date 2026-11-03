import unittest

from granary import budget
from granary import survey
from granary import payroll
from granary import metrics
from granary import summary


class Hidden(unittest.TestCase):
    def test_budget_truncate_words(self):
        self.assertEqual(budget.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(budget.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(budget.truncate_words('', 3), '')
        self.assertEqual(budget.truncate_words('one two three', 1), 'one...')

    def test_budget_format_cents(self):
        self.assertEqual(budget.format_cents(0), '$0.00')
        self.assertEqual(budget.format_cents(123456), '$1,234.56')
        self.assertEqual(budget.format_cents(-105), '-$1.05')
        self.assertEqual(budget.format_cents(5), '$0.05')
        self.assertEqual(budget.format_cents(100000000), '$1,000,000.00')

    def test_budget_weighted_mean(self):
        self.assertEqual(budget.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(budget.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(budget.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            budget.weighted_mean([5, 5], [0, 0])
        self.assertEqual(budget.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_survey_top_n(self):
        self.assertEqual(survey.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(survey.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(survey.top_n({}, 2), [])
        self.assertEqual(survey.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_survey_dedupe(self):
        self.assertEqual(survey.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(survey.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(survey.dedupe([]), [])
        self.assertEqual(survey.dedupe([1, 1, 1]), [1])

    def test_survey_moving_average(self):
        self.assertEqual(survey.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(survey.moving_average([5], 1), [5.0])
        self.assertEqual(survey.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(survey.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            survey.moving_average([1, 2], 0)

    def test_payroll_word_count(self):
        self.assertEqual(payroll.word_count('a b'), 2)
        self.assertEqual(payroll.word_count('  tea  and   milk '), 3)
        self.assertEqual(payroll.word_count(''), 0)
        self.assertEqual(payroll.word_count('one'), 1)

    def test_payroll_paginate(self):
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(payroll.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            payroll.paginate([1, 2], 0, 2)

    def test_metrics_chunk(self):
        self.assertEqual(metrics.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(metrics.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(metrics.chunk([], 3), [])
        self.assertEqual(metrics.chunk(['a'], 1), [['a']])
        self.assertEqual(metrics.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            metrics.chunk([1, 2], 0)

    def test_metrics_luhn_valid(self):
        self.assertEqual(metrics.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(metrics.luhn_valid('79927398713'), True)
        self.assertEqual(metrics.luhn_valid('79927398710'), False)
        self.assertEqual(metrics.luhn_valid(''), False)
        self.assertEqual(metrics.luhn_valid('059'), True)

    def test_metrics_grade(self):
        self.assertEqual(metrics.grade(95), 'A')
        self.assertEqual(metrics.grade(90), 'A')
        self.assertEqual(metrics.grade(85), 'B')
        self.assertEqual(metrics.grade(80), 'B')
        self.assertEqual(metrics.grade(61), 'D')
        self.assertEqual(metrics.grade(59), 'F')
        self.assertEqual(metrics.grade(0), 'F')

    def test_summary_cargo_check(self):
        self.assertEqual(summary.cargo_check('the quick brown fox', 2), {'cargo_check': 'the quick...'})
        self.assertEqual(summary.cargo_check('tea time', 2), {'cargo_check': 'tea time'})
        self.assertEqual(summary.cargo_check('', 3), {'cargo_check': ''})
        self.assertEqual(summary.cargo_check('one two three', 1), {'cargo_check': 'one...'})

    def test_summary_mooring_entry(self):
        self.assertEqual(summary.mooring_entry(0), {'mooring_entry': '$0.00'})
        self.assertEqual(summary.mooring_entry(123456), {'mooring_entry': '$1,234.56'})
        self.assertEqual(summary.mooring_entry(-105), {'mooring_entry': '-$1.05'})
        self.assertEqual(summary.mooring_entry(5), {'mooring_entry': '$0.05'})
        self.assertEqual(summary.mooring_entry(100000000), {'mooring_entry': '$1,000,000.00'})

    def test_summary_sail_total(self):
        self.assertEqual(summary.sail_total([1, 2, 3], [1, 1, 1]), {'sail_total': 2.0})
        self.assertEqual(summary.sail_total([10, 20], [1, 3]), {'sail_total': 17.5})
        self.assertEqual(summary.sail_total([4], [2]), {'sail_total': 4.0})
        with self.assertRaises(ValueError):
            summary.sail_total([5, 5], [0, 0])
        self.assertEqual(summary.sail_total([1, 2], [0.5, 1.5]), {'sail_total': 1.75})

    def test_summary_sail_check(self):
        self.assertEqual(summary.sail_check({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'sail_check': ['milk', 'tea']})
        self.assertEqual(summary.sail_check({'a': 1}, 5), {'sail_check': ['a']})
        self.assertEqual(summary.sail_check({}, 2), {'sail_check': []})
        self.assertEqual(summary.sail_check({'x': 2, 'y': 5, 'z': 2}, 2), {'sail_check': ['y', 'x']})

    def test_summary_cargo_summary(self):
        self.assertEqual(summary.cargo_summary([3, 1, 3, 2, 1]), {'cargo_summary': [3, 1, 2]})
        self.assertEqual(summary.cargo_summary(['b', 'a', 'b']), {'cargo_summary': ['b', 'a']})
        self.assertEqual(summary.cargo_summary([]), {'cargo_summary': []})
        self.assertEqual(summary.cargo_summary([1, 1, 1]), {'cargo_summary': [1]})
