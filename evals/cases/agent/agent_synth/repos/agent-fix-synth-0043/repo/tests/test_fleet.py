import unittest

from meadow import fleet


class Fleet(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(fleet.percent_change(50, 75), 50.0)
        self.assertEqual(fleet.percent_change(200, 150), -25.0)

    def test_luhn_valid(self):
        self.assertEqual(fleet.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(fleet.luhn_valid('79927398713'), True)
