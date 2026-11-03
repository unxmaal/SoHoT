import unittest

from tally import timesheet


class Timesheet(unittest.TestCase):
    def test_running_total(self):
        self.assertEqual(timesheet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(timesheet.running_total([]), [])

    def test_moving_average(self):
        self.assertEqual(timesheet.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(timesheet.moving_average([5], 1), [5.0])
        self.assertEqual(timesheet.moving_average([1, 2, 3], 3), [2.0])
