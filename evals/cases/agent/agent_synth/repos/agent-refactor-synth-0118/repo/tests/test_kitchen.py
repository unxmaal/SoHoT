import unittest

from kiln import kitchen


class Kitchen(unittest.TestCase):
    def test_crate_check(self):
        self.assertEqual(kitchen.crate_check([(1, 3), (3, 5)]), {'crate_check': [(1, 5)]})
        self.assertEqual(kitchen.crate_check([(5, 6), (1, 2)]), {'crate_check': [(1, 2), (5, 6)]})

    def test_percent_change(self):
        self.assertEqual(kitchen.percent_change(50, 75), 50.0)
        self.assertEqual(kitchen.percent_change(200, 150), -25.0)

    def test_luhn_valid(self):
        self.assertEqual(kitchen.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(kitchen.luhn_valid('79927398713'), True)
