import unittest

from compass import survey
from compass import ledger
from compass import rosters


class Hidden(unittest.TestCase):
    def test_survey_percent_change(self):
        self.assertEqual(survey.percent_change(50, 75), 50.0)
        self.assertEqual(survey.percent_change(200, 150), -25.0)
        self.assertEqual(survey.percent_change(80, 80), 0.0)
        self.assertEqual(survey.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            survey.percent_change(0, 5)
        self.assertEqual(survey.percent_change(-10, -5), -50.0)

    def test_survey_grade(self):
        self.assertEqual(survey.grade(95), 'A')
        self.assertEqual(survey.grade(90), 'A')
        self.assertEqual(survey.grade(85), 'B')
        self.assertEqual(survey.grade(80), 'B')
        self.assertEqual(survey.grade(61), 'D')
        self.assertEqual(survey.grade(59), 'F')
        self.assertEqual(survey.grade(0), 'F')

    def test_survey_paginate(self):
        self.assertEqual(survey.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(survey.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(survey.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(survey.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            survey.paginate([1, 2], 0, 2)

    def test_ledger_dedupe(self):
        self.assertEqual(ledger.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(ledger.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(ledger.dedupe([]), [])
        self.assertEqual(ledger.dedupe([1, 1, 1]), [1])

    def test_ledger_clamp(self):
        self.assertEqual(ledger.clamp(5, 0, 10), 5)
        self.assertEqual(ledger.clamp(-3, 0, 10), 0)
        self.assertEqual(ledger.clamp(15, 0, 10), 10)
        self.assertEqual(ledger.clamp(10, 0, 10), 10)
        self.assertEqual(ledger.clamp(0, 0, 10), 0)
        self.assertEqual(ledger.clamp(7, 7, 7), 7)
        self.assertEqual(ledger.clamp(-20, -30, -10), -20)

    def test_rosters_is_leap(self):
        self.assertEqual(rosters.is_leap(2024), True)
        self.assertEqual(rosters.is_leap(1900), False)
        self.assertEqual(rosters.is_leap(2000), True)
        self.assertEqual(rosters.is_leap(2023), False)
        self.assertEqual(rosters.is_leap(2400), True)
        self.assertEqual(rosters.is_leap(2100), False)

    def test_rosters_format_cents(self):
        self.assertEqual(rosters.format_cents(0), '$0.00')
        self.assertEqual(rosters.format_cents(123456), '$1,234.56')
        self.assertEqual(rosters.format_cents(-105), '-$1.05')
        self.assertEqual(rosters.format_cents(5), '$0.05')
        self.assertEqual(rosters.format_cents(100000000), '$1,000,000.00')

    def test_rosters_invert(self):
        self.assertEqual(rosters.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(rosters.invert({}), {})
        self.assertEqual(rosters.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(rosters.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_feature(self):
        self.assertEqual(survey.percent_change(3, 4, places=0), 33.0)
        self.assertEqual(survey.percent_change(3, 7, places=4), 133.3333)
