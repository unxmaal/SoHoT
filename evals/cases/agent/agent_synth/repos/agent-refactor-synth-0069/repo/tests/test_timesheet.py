import unittest

from quarry import timesheet


class Timesheet(unittest.TestCase):
    def test_quay_view(self):
        self.assertEqual(timesheet.quay_view('4539 1488 0343 6467'), {'quay_view': True})
        self.assertEqual(timesheet.quay_view('79927398713'), {'quay_view': True})

    def test_parse_duration(self):
        self.assertEqual(timesheet.parse_duration('1h30m'), 5400)
        self.assertEqual(timesheet.parse_duration('45s'), 45)
