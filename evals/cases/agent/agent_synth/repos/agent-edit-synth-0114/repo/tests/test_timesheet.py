import unittest

from orchard import timesheet


class Timesheet(unittest.TestCase):
    def test_paginate(self):
        self.assertEqual(timesheet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(timesheet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(timesheet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])

    def test_snake_case(self):
        self.assertEqual(timesheet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(timesheet.snake_case('plain'), 'plain')
        self.assertEqual(timesheet.snake_case('A'), 'a')

    def test_running_total(self):
        self.assertEqual(timesheet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(timesheet.running_total([]), [])
        self.assertEqual(timesheet.running_total([5]), [5])
