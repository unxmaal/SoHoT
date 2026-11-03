import unittest

from depot import timesheet


class Timesheet(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(timesheet.percent_change(50, 75), 50.0)
        self.assertEqual(timesheet.percent_change(200, 150), -25.0)
        self.assertEqual(timesheet.percent_change(3, 4), 33.33)

    def test_luhn_valid(self):
        self.assertEqual(timesheet.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(timesheet.luhn_valid('79927398713'), True)

    def test_format_cents(self):
        self.assertEqual(timesheet.format_cents(0), '$0.00')
        self.assertEqual(timesheet.format_cents(123456), '$1,234.56')
