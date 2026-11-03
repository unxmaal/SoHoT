import unittest

from kiln import metrics
from kiln import kitchen
from kiln import timesheet
from kiln import rosters


class Hidden(unittest.TestCase):
    def test_metrics_format_cents(self):
        self.assertEqual(metrics.format_cents(0), '$0.00')
        self.assertEqual(metrics.format_cents(123456), '$1,234.56')
        self.assertEqual(metrics.format_cents(-105), '-$1.05')
        self.assertEqual(metrics.format_cents(5), '$0.05')
        self.assertEqual(metrics.format_cents(100000000), '$1,000,000.00')

    def test_metrics_paginate(self):
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(metrics.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            metrics.paginate([1, 2], 0, 2)

    def test_kitchen_top_n(self):
        self.assertEqual(kitchen.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(kitchen.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(kitchen.top_n({}, 2), [])
        self.assertEqual(kitchen.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_kitchen_truncate_words(self):
        self.assertEqual(kitchen.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(kitchen.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(kitchen.truncate_words('', 3), '')
        self.assertEqual(kitchen.truncate_words('one two three', 1), 'one...')

    def test_timesheet_is_leap(self):
        self.assertEqual(timesheet.is_leap(2024), True)
        self.assertEqual(timesheet.is_leap(1900), False)
        self.assertEqual(timesheet.is_leap(2000), True)
        self.assertEqual(timesheet.is_leap(2023), False)
        self.assertEqual(timesheet.is_leap(2400), True)
        self.assertEqual(timesheet.is_leap(2100), False)

    def test_timesheet_running_total(self):
        self.assertEqual(timesheet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(timesheet.running_total([]), [])
        self.assertEqual(timesheet.running_total([5]), [5])
        self.assertEqual(timesheet.running_total([2, -2, 2]), [2, 0, 2])

    def test_timesheet_grade(self):
        self.assertEqual(timesheet.grade(95), 'A')
        self.assertEqual(timesheet.grade(90), 'A')
        self.assertEqual(timesheet.grade(85), 'B')
        self.assertEqual(timesheet.grade(80), 'B')
        self.assertEqual(timesheet.grade(61), 'D')
        self.assertEqual(timesheet.grade(59), 'F')
        self.assertEqual(timesheet.grade(0), 'F')

    def test_rosters_dedupe(self):
        self.assertEqual(rosters.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(rosters.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(rosters.dedupe([]), [])
        self.assertEqual(rosters.dedupe([1, 1, 1]), [1])

    def test_rosters_word_count(self):
        self.assertEqual(rosters.word_count('a b'), 2)
        self.assertEqual(rosters.word_count('  tea  and   milk '), 3)
        self.assertEqual(rosters.word_count(''), 0)
        self.assertEqual(rosters.word_count('one'), 1)

    def test_feature(self):
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], -1, 3), [10])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9], -1, 3), [7, 8, 9])
        self.assertEqual(metrics.paginate([], -1, 4), [])
