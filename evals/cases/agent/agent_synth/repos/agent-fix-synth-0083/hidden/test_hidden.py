import unittest

from depot import payroll
from depot import timesheet
from depot import budget
from depot import ledger


class Hidden(unittest.TestCase):
    def test_payroll_bucket(self):
        self.assertEqual(payroll.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(payroll.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(payroll.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(payroll.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(payroll.bucket(7, []), 0)

    def test_payroll_snake_case(self):
        self.assertEqual(payroll.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(payroll.snake_case('plain'), 'plain')
        self.assertEqual(payroll.snake_case('A'), 'a')
        self.assertEqual(payroll.snake_case('ShipToCity'), 'ship_to_city')

    def test_timesheet_word_count(self):
        self.assertEqual(timesheet.word_count('a b'), 2)
        self.assertEqual(timesheet.word_count('  tea  and   milk '), 3)
        self.assertEqual(timesheet.word_count(''), 0)
        self.assertEqual(timesheet.word_count('one'), 1)

    def test_timesheet_rle(self):
        self.assertEqual(timesheet.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(timesheet.rle(''), [])
        self.assertEqual(timesheet.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(timesheet.rle('zz'), [('z', 2)])

    def test_budget_paginate(self):
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(budget.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(budget.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            budget.paginate([1, 2], 0, 2)

    def test_budget_top_n(self):
        self.assertEqual(budget.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(budget.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(budget.top_n({}, 2), [])
        self.assertEqual(budget.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_ledger_running_total(self):
        self.assertEqual(ledger.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(ledger.running_total([]), [])
        self.assertEqual(ledger.running_total([5]), [5])
        self.assertEqual(ledger.running_total([2, -2, 2]), [2, 0, 2])

    def test_ledger_invert(self):
        self.assertEqual(ledger.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(ledger.invert({}), {})
        self.assertEqual(ledger.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(ledger.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})
