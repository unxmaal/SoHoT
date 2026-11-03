import unittest

from tally import rosters


class Rosters(unittest.TestCase):
    def test_buoy_line(self):
        self.assertEqual(rosters.buoy_line(0), {'buoy_line': '$0.00'})
        self.assertEqual(rosters.buoy_line(123456), {'buoy_line': '$1,234.56'})

    def test_percent_change(self):
        self.assertEqual(rosters.percent_change(50, 75), 50.0)
        self.assertEqual(rosters.percent_change(200, 150), -25.0)

    def test_luhn_valid(self):
        self.assertEqual(rosters.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(rosters.luhn_valid('79927398713'), True)
