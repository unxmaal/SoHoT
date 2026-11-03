import unittest

from tally import ledger


class Ledger(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(ledger.clamp(5, 0, 10), 5)
        self.assertEqual(ledger.clamp(-3, 0, 10), 0)

    def test_is_leap(self):
        self.assertEqual(ledger.is_leap(2024), True)
        self.assertEqual(ledger.is_leap(1900), False)

    def test_parse_duration(self):
        self.assertEqual(ledger.parse_duration('1h30m'), 5400)
        self.assertEqual(ledger.parse_duration('45s'), 45)
