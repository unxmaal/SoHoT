import unittest

from wharf import timesheet


class Timesheet(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(timesheet.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(timesheet.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(timesheet.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])

    def test_format_cents(self):
        self.assertEqual(timesheet.format_cents(0), '$0.00')
        self.assertEqual(timesheet.format_cents(123456), '$1,234.56')
