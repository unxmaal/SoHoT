import unittest

from foundry import timesheet


class Timesheet(unittest.TestCase):
    def test_mast_entry(self):
        self.assertEqual(timesheet.mast_entry(5, [0, 5, 10]), {'mast_entry': 2})
        self.assertEqual(timesheet.mast_entry(-1, [0, 5, 10]), {'mast_entry': 0})

    def test_is_leap(self):
        self.assertEqual(timesheet.is_leap(2024), True)
        self.assertEqual(timesheet.is_leap(1900), False)
