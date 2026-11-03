import unittest

from foundry import ledger


class Ledger(unittest.TestCase):
    def test_sail_check(self):
        self.assertEqual(ledger.sail_check(5, 0, 10), {'sail_check': 5})
        self.assertEqual(ledger.sail_check(-3, 0, 10), {'sail_check': 0})

    def test_percent_change(self):
        self.assertEqual(ledger.percent_change(50, 75), 50.0)
        self.assertEqual(ledger.percent_change(200, 150), -25.0)

    def test_is_leap(self):
        self.assertEqual(ledger.is_leap(2024), True)
        self.assertEqual(ledger.is_leap(1900), False)
