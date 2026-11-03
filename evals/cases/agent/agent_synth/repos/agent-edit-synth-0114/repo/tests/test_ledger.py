import unittest

from orchard import ledger


class Ledger(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(ledger.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(ledger.luhn_valid('79927398713'), True)
        self.assertEqual(ledger.luhn_valid('79927398710'), False)

    def test_parse_duration(self):
        self.assertEqual(ledger.parse_duration('1h30m'), 5400)
        self.assertEqual(ledger.parse_duration('45s'), 45)
        self.assertEqual(ledger.parse_duration('2h'), 7200)

    def test_median(self):
        self.assertEqual(ledger.median([3, 1, 2]), 2)
        self.assertEqual(ledger.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(ledger.median([5]), 5)
