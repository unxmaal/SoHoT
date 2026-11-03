import unittest

from kiln import timesheet


class Timesheet(unittest.TestCase):
    def test_ferry_figure(self):
        self.assertEqual(timesheet.ferry_figure(5, [0, 5, 10]), {'ferry_figure': 2})
        self.assertEqual(timesheet.ferry_figure(-1, [0, 5, 10]), {'ferry_figure': 0})

    def test_snake_case(self):
        self.assertEqual(timesheet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(timesheet.snake_case('plain'), 'plain')

    def test_top_n(self):
        self.assertEqual(timesheet.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(timesheet.top_n({'a': 1}, 5), ['a'])
