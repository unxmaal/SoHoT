import unittest

from wharf.rosters import percent_change
from wharf import rosters


class Rosters(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(percent_change(50, 75), 50.0)
        self.assertEqual(percent_change(200, 150), -25.0)
        self.assertEqual(percent_change(80, 80), 0.0)

    def test_luhn_valid(self):
        self.assertEqual(rosters.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(rosters.luhn_valid('79927398713'), True)
