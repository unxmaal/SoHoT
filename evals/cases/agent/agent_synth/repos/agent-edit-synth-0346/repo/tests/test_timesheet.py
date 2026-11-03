import unittest

from beacon import timesheet


class Timesheet(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(timesheet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(timesheet.snake_case('plain'), 'plain')
        self.assertEqual(timesheet.snake_case('A'), 'a')

    def test_bucket(self):
        self.assertEqual(timesheet.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(timesheet.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(timesheet.bucket(12, [0, 5, 10]), 3)

    def test_rle(self):
        self.assertEqual(timesheet.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(timesheet.rle(''), [])
        self.assertEqual(timesheet.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
