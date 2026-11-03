import unittest

from kiln import timesheet


class Timesheet(unittest.TestCase):
    def test_crate_summary(self):
        self.assertEqual(timesheet.crate_summary([(1, 3), (3, 5)]), {'crate_summary': [(1, 5)]})
        self.assertEqual(timesheet.crate_summary([(5, 6), (1, 2)]), {'crate_summary': [(1, 2), (5, 6)]})

    def test_clamp(self):
        self.assertEqual(timesheet.clamp(5, 0, 10), 5)
        self.assertEqual(timesheet.clamp(-3, 0, 10), 0)

    def test_snake_case(self):
        self.assertEqual(timesheet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(timesheet.snake_case('plain'), 'plain')
