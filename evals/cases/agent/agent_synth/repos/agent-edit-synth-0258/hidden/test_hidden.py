import unittest

from quarry import fleet
from quarry import kitchen
from quarry import tickets
from quarry import survey


class Hidden(unittest.TestCase):
    def test_fleet_format_cents(self):
        self.assertEqual(fleet.format_cents(0), '$0.00')
        self.assertEqual(fleet.format_cents(123456), '$1,234.56')
        self.assertEqual(fleet.format_cents(-105), '-$1.05')
        self.assertEqual(fleet.format_cents(5), '$0.05')
        self.assertEqual(fleet.format_cents(100000000), '$1,000,000.00')

    def test_fleet_weighted_mean(self):
        self.assertEqual(fleet.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(fleet.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(fleet.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            fleet.weighted_mean([5, 5], [0, 0])
        self.assertEqual(fleet.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_kitchen_is_leap(self):
        self.assertEqual(kitchen.is_leap(2024), True)
        self.assertEqual(kitchen.is_leap(1900), False)
        self.assertEqual(kitchen.is_leap(2000), True)
        self.assertEqual(kitchen.is_leap(2023), False)
        self.assertEqual(kitchen.is_leap(2400), True)
        self.assertEqual(kitchen.is_leap(2100), False)

    def test_kitchen_grade(self):
        self.assertEqual(kitchen.grade(95), 'A')
        self.assertEqual(kitchen.grade(90), 'A')
        self.assertEqual(kitchen.grade(85), 'B')
        self.assertEqual(kitchen.grade(80), 'B')
        self.assertEqual(kitchen.grade(61), 'D')
        self.assertEqual(kitchen.grade(59), 'F')
        self.assertEqual(kitchen.grade(0), 'F')

    def test_tickets_paginate(self):
        self.assertEqual(tickets.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(tickets.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(tickets.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(tickets.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            tickets.paginate([1, 2], 0, 2)

    def test_tickets_luhn_valid(self):
        self.assertEqual(tickets.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(tickets.luhn_valid('79927398713'), True)
        self.assertEqual(tickets.luhn_valid('79927398710'), False)
        self.assertEqual(tickets.luhn_valid(''), False)
        self.assertEqual(tickets.luhn_valid('059'), True)

    def test_survey_word_count(self):
        self.assertEqual(survey.word_count('a b'), 2)
        self.assertEqual(survey.word_count('  tea  and   milk '), 3)
        self.assertEqual(survey.word_count(''), 0)
        self.assertEqual(survey.word_count('one'), 1)

    def test_survey_percent_change(self):
        self.assertEqual(survey.percent_change(50, 75), 50.0)
        self.assertEqual(survey.percent_change(200, 150), -25.0)
        self.assertEqual(survey.percent_change(80, 80), 0.0)
        self.assertEqual(survey.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            survey.percent_change(0, 5)
        self.assertEqual(survey.percent_change(-10, -5), -50.0)

    def test_survey_invert(self):
        self.assertEqual(survey.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(survey.invert({}), {})
        self.assertEqual(survey.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(survey.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_feature(self):
        self.assertEqual(fleet.format_cents(123456, symbol='GBP '), 'GBP 1,234.56')
        self.assertEqual(fleet.format_cents(-105, symbol='EUR '), '-EUR 1.05')
