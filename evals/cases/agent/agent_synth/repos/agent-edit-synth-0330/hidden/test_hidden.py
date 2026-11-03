import unittest

from wharf import ledger
from wharf import budget
from wharf import survey
from wharf import tickets


class Hidden(unittest.TestCase):
    def test_ledger_format_cents(self):
        self.assertEqual(ledger.format_cents(0), '$0.00')
        self.assertEqual(ledger.format_cents(123456), '$1,234.56')
        self.assertEqual(ledger.format_cents(-105), '-$1.05')
        self.assertEqual(ledger.format_cents(5), '$0.05')
        self.assertEqual(ledger.format_cents(100000000), '$1,000,000.00')

    def test_ledger_grade(self):
        self.assertEqual(ledger.grade(95), 'A')
        self.assertEqual(ledger.grade(90), 'A')
        self.assertEqual(ledger.grade(85), 'B')
        self.assertEqual(ledger.grade(80), 'B')
        self.assertEqual(ledger.grade(61), 'D')
        self.assertEqual(ledger.grade(59), 'F')
        self.assertEqual(ledger.grade(0), 'F')

    def test_ledger_bucket(self):
        self.assertEqual(ledger.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(ledger.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(ledger.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(ledger.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(ledger.bucket(7, []), 0)

    def test_budget_paginate(self):
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(budget.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            budget.paginate([1, 2], 0, 2)

    def test_budget_luhn_valid(self):
        self.assertEqual(budget.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(budget.luhn_valid('79927398713'), True)
        self.assertEqual(budget.luhn_valid('79927398710'), False)
        self.assertEqual(budget.luhn_valid(''), False)
        self.assertEqual(budget.luhn_valid('059'), True)

    def test_survey_rle(self):
        self.assertEqual(survey.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(survey.rle(''), [])
        self.assertEqual(survey.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(survey.rle('zz'), [('z', 2)])

    def test_survey_is_leap(self):
        self.assertEqual(survey.is_leap(2024), True)
        self.assertEqual(survey.is_leap(1900), False)
        self.assertEqual(survey.is_leap(2000), True)
        self.assertEqual(survey.is_leap(2023), False)
        self.assertEqual(survey.is_leap(2400), True)
        self.assertEqual(survey.is_leap(2100), False)

    def test_survey_truncate_words(self):
        self.assertEqual(survey.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(survey.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(survey.truncate_words('', 3), '')
        self.assertEqual(survey.truncate_words('one two three', 1), 'one...')

    def test_tickets_word_count(self):
        self.assertEqual(tickets.word_count('a b'), 2)
        self.assertEqual(tickets.word_count('  tea  and   milk '), 3)
        self.assertEqual(tickets.word_count(''), 0)
        self.assertEqual(tickets.word_count('one'), 1)

    def test_tickets_invert(self):
        self.assertEqual(tickets.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(tickets.invert({}), {})
        self.assertEqual(tickets.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(tickets.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_tickets_top_n(self):
        self.assertEqual(tickets.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(tickets.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(tickets.top_n({}, 2), [])
        self.assertEqual(tickets.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_feature(self):
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], -1, 3), [10])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9], -1, 3), [7, 8, 9])
        self.assertEqual(budget.paginate([], -1, 4), [])
