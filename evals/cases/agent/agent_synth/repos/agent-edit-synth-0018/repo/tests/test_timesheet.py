import unittest

from kiln import timesheet


class Timesheet(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(timesheet.is_leap(2024), True)
        self.assertEqual(timesheet.is_leap(1900), False)
        self.assertEqual(timesheet.is_leap(2000), True)

    def test_running_total(self):
        self.assertEqual(timesheet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(timesheet.running_total([]), [])
        self.assertEqual(timesheet.running_total([5]), [5])

    def test_grade(self):
        self.assertEqual(timesheet.grade(95), 'A')
        self.assertEqual(timesheet.grade(90), 'A')
        self.assertEqual(timesheet.grade(85), 'B')
