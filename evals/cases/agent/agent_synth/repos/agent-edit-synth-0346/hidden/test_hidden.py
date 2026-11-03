import unittest

from beacon import timesheet
from beacon import budget


class Hidden(unittest.TestCase):
    def test_timesheet_snake_case(self):
        self.assertEqual(timesheet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(timesheet.snake_case('plain'), 'plain')
        self.assertEqual(timesheet.snake_case('A'), 'a')
        self.assertEqual(timesheet.snake_case('ShipToCity'), 'ship_to_city')

    def test_timesheet_bucket(self):
        self.assertEqual(timesheet.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(timesheet.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(timesheet.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(timesheet.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(timesheet.bucket(7, []), 0)

    def test_timesheet_rle(self):
        self.assertEqual(timesheet.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(timesheet.rle(''), [])
        self.assertEqual(timesheet.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(timesheet.rle('zz'), [('z', 2)])

    def test_budget_word_count(self):
        self.assertEqual(budget.word_count('a b'), 2)
        self.assertEqual(budget.word_count('  tea  and   milk '), 3)
        self.assertEqual(budget.word_count(''), 0)
        self.assertEqual(budget.word_count('one'), 1)

    def test_budget_paginate(self):
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(budget.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            budget.paginate([1, 2], 0, 2)

    def test_budget_merge_ranges(self):
        self.assertEqual(budget.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(budget.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(budget.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(budget.merge_ranges([]), [])
        self.assertEqual(budget.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_feature(self):
        self.assertEqual(budget.merge_ranges([(1, 2), (3, 4)]), [(1, 4)])
        self.assertEqual(budget.merge_ranges([(7, 9), (1, 6)]), [(1, 9)])
